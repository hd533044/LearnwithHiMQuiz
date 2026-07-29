import logging
import asyncio
from telegram import (
    Update, Poll, InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler, CallbackQueryHandler, 
    ContextTypes, ConversationHandler, MessageHandler, filters
)
from app.config import BOT_TOKEN, CHANNEL_USERNAME, DAILY_QUESTION_LIMIT, ADMIN_IDS
from app.database import (
    init_db, save_user_profile, get_user_profile, get_today_attempts
)
from app.stats import get_quiz_toppers, calculate_user_rank, calculate_overall_performance
from app.quiz_engine import start_quiz_session, get_active_session, finish_quiz_session

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Global Session & Timer Storage
POLL_SESSION_MAP = {}
QUIZ_SETUP_CACHE = {}
TIMER_TASKS = {}

# Onboarding Conversation States (5 Steps)
NAME, TARGET_EXAM, PHONE_OTP, AGE_STEP, GENDER_STEP = range(5)

BOT_BRANDING_HEADER = "📚 Learn with HiM Quiz Book\n*(The best in class Quiz Creator by Himanshu Sir)* ❤️\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Universal Reply Menu Keyboard (Commands placed first so Telegram handles clicks natively)
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["/quiz 🚀", "/help 📊"],
            ["/hello 👋", "/myprofile 👤"],
            ["/myrank 🥇", "/myperformance 📈"],
            ["/mywholestate 🎓", "/toppersname 🏆"]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

# =====================================================================
#                        ONBOARDING WIZARD
# =====================================================================

async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    # Check if user came via deep link from group (?start=quiz)
    is_deep_link_quiz = bool(args and args[0] == "quiz")

    try:
        raw_profile = get_user_profile(user.id)
        profile = dict(raw_profile) if raw_profile else {}
        
        if profile.get("is_verified"):
            full_name = profile.get("full_name") or user.full_name
            target_exam = profile.get("target_exam") or "General"
            
            # If triggered via ?start=quiz deep link, launch quiz directly!
            if is_deep_link_quiz:
                await quiz_command(update, context)
                return ConversationHandler.END

            msg = (
                f"{BOT_BRANDING_HEADER}\n\n"
                f"👋 **Welcome back, {full_name}!**\n\n"
                f"🎯 **Target Exam:** `{target_exam}`\n"
                f"📊 **Daily Target Quota:** `{DAILY_QUESTION_LIMIT} Questions/day`\n\n"
                f"📌 **Quick Navigation:**\n"
                f"• Tap any menu button below or use direct commands:\n"
                f"  └ /quiz — Start a practice test\n"
                f"  └ /hello — Personalized greeting & motivation\n"
                f"  └ /mywholestate — Academic report\n"
                f"  └ /toppersname — Global Leaderboard\n\n"
                f"📢 **Official Channel:** {CHANNEL_USERNAME}"
            )
            await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
            return ConversationHandler.END
    except Exception as e:
        logging.error(f"Error checking profile in start_onboarding: {e}")

    welcome_msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"Master Computer Awareness & Exam PYQs with **Himanshu Sir**!\n"
        f"Targeting **SSC CGL, CHSL, CAPF HCM, Delhi Police, UPSI & Railways**.\n\n"
        f"📝 **Student Registration (Step 1/5)**\n"
        f"Please reply with your **Full Name** to setup your official student profile:"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")
    return NAME

async def name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name_text = update.message.text.strip()
        context.user_data["full_name"] = name_text

        exams = [
            ["1. SSC CGL", "2. SSC CHSL"],
            ["3. DSSSB", "4. CAPF HCM AND ASI STENO"],
            ["5. DELHI POLICE HCM", "6. UPSI / UP-CONST"],
            ["7. RAILWAYS", "8. SSC CGL MAINS"],
            ["9. SSC CHSL MAINS", "10. OTHER EXAMS"]
        ]
        markup = ReplyKeyboardMarkup(exams, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            f"Pleasure to onboard you, *{name_text}*! ✨\n\n"
            f"🎯 **Select Target Exam (Step 2/5)**\n"
            f"Please choose your primary target exam from the options below:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        return TARGET_EXAM
    except Exception as e:
        logging.error(f"Error in name_step: {e}")
        await update.message.reply_text("Please reply with your Full Name to continue:")
        return NAME

async def target_exam_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        exam_text = update.message.text.strip()
        context.user_data["target_exam"] = exam_text
        
        contact_btn = KeyboardButton(text="📱 Share Verified Mobile Number", request_contact=True)
        markup = ReplyKeyboardMarkup([[contact_btn]], one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            f"🎯 Selected Target: `{exam_text}`\n\n"
            f"📱 **Mobile Verification (Step 3/5)**\n"
            f"Click the button below to share your mobile number securely:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        return PHONE_OTP
    except Exception as e:
        logging.error(f"Error in target_exam_step: {e}")
        await update.message.reply_text("Please select your target exam using the options provided:")
        return TARGET_EXAM

async def phone_otp_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.contact:
            phone = update.message.contact.phone_number
        else:
            phone = update.message.text.strip()
            
        context.user_data["phone_number"] = phone
        
        await update.message.reply_text(
            f"✅ Contact Verified: `{phone}`\n\n"
            f"👤 **Student Age (Step 4/5)**\n"
            f"Please reply with your **Age** in years (e.g. `22`):",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return AGE_STEP
    except Exception as e:
        logging.error(f"Error in phone_otp_step: {e}")
        return PHONE_OTP

async def age_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        age = int(text) if text.isdigit() else 21
        context.user_data["age"] = age

        gender_keyboard = [["Male", "Female"], ["Other"]]
        markup = ReplyKeyboardMarkup(gender_keyboard, one_time_keyboard=True, resize_keyboard=True)

        await update.message.reply_text(
            f"👤 **Gender Selection (Step 5/5)**\n"
            f"Please choose your **Gender** from the menu below:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        return GENDER_STEP
    except Exception as e:
        logging.error(f"Error in age_step: {e}")
        await update.message.reply_text("Please enter a valid age in numbers (e.g. 22):")
        return AGE_STEP

async def gender_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        gender_text = update.message.text.strip()
        user = update.effective_user
        
        save_user_profile(
            user_id=user.id,
            full_name=context.user_data.get("full_name", user.full_name),
            username=user.username or "N/A",
            phone=context.user_data.get("phone_number", "N/A"),
            target_exam=context.user_data.get("target_exam", "General"),
            age=context.user_data.get("age", 21),
            gender=gender_text
        )
        
        completion_msg = (
            f"{BOT_BRANDING_HEADER}\n\n"
            f"🎉 **Registration Complete!**\n\n"
            f"Your student profile has been created successfully.\n\n"
            f"👉 **Tap /quiz below or use the main menu to begin practicing!**"
        )
        await update.message.reply_text(completion_msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END
    except Exception as e:
        logging.error(f"Error in gender_step: {e}")
        await update.message.reply_text("Profile saved! Type /quiz to start practicing.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

async def cancel_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Setup cancelled. Type /start anytime to begin registration.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# =====================================================================
#                        NEW /hello GREETING COMMAND
# =====================================================================

async def hello_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}

    full_name = profile.get("full_name") or user.full_name
    age = profile.get("age") or "N/A"
    gender = profile.get("gender") or "Student"
    target_exam = profile.get("target_exam") or "Competitive Exams"

    # Gender salutation styling
    gender_str = str(gender).lower()
    salutation = "Mr." if "male" in gender_str and "female" not in gender_str else "Ms." if "female" in gender_str else "Dear"

    greeting_msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"👋 **Greetings & Warm Welcome, {salutation} {full_name}!** ❤️\n\n"
        f"👤 **Student Info:**\n"
        f"• **Age:** `{age} years old`\n"
        f"• **Gender:** `{gender}`\n"
        f"• **Targeting:** `{target_exam}`\n\n"
        f"🌟 **A Message From Himanshu Sir:**\n"
        f"\"Stay focused, keep practicing daily, and believe in your hard work! \"\n\n"
        f"🎯 **May you secure your dream job in `{target_exam}` this year!** 🏆\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Select an option from the menu below to start practicing:"
    )
    await update.message.reply_text(greeting_msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

# =====================================================================
#                           CORE QUIZ LOGIC
# =====================================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    clean_channel = CHANNEL_USERNAME.replace("@", "")
    
    keyboard = [
        [InlineKeyboardButton("🚀 Launch Quiz", callback_data="quick_cmd_quiz"), InlineKeyboardButton("👋 Personal Greeting", callback_data="quick_cmd_hello")],
        [InlineKeyboardButton("👤 My Profile", callback_data="quick_cmd_profile"), InlineKeyboardButton("🥇 Check Rank", callback_data="quick_cmd_rank")],
        [InlineKeyboardButton("🏆 Top Leaderboard", callback_data="quick_cmd_toppers"), InlineKeyboardButton("🎓 Full Report", callback_data="quick_cmd_state")],
        [InlineKeyboardButton("📢 Join Official Channel", url=f"https://t.me/{clean_channel}")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"👋 **Hello, {user.full_name}!**\n"
        f"Welcome to your personal learning & evaluation portal.\n\n"
        f"🤖 **Platform Features:**\n"
        f"• 📚 100% Verified, Non-Repeating PYQs\n"
        f"• 🎯 Question Limits: 10, 15, 20, 25, or 30 Questions\n"
        f"• ⏱ Custom Timers: 12s, 15s, 18s, or 20s per question\n"
        f"• ⏸ Full Session Control: /stop & /resume\n"
        f"• 📈 Practice Quota: Up to `{DAILY_QUESTION_LIMIT}` questions daily\n\n"
        f"📌 **Available Commands (Tap to execute):**\n"
        f"• /quiz — Start a computer awareness mock test\n"
        f"• /hello — Personalized motivational greeting\n"
        f"• /stop — Pause your active session\n"
        f"• /resume — Resume your paused session\n"
        f"• /myprofile — View student profile card\n"
        f"• /myrank — View your global rank\n"
        f"• /myperformance — Performance grading\n"
        f"• /mywholestate — Complete academic progress report\n"
        f"• /toppersname — Public Top 10 Leaderboard\n\n"
        f"👇 **Tap any button below for instant access:**"
    )
    await update.message.reply_text(msg, reply_markup=markup, parse_mode="Markdown")

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    # GROUP CHECK: Redirect group calls to a private URL button
    if chat and chat.type in ["group", "supergroup"]:
        bot_username = context.bot.username
        private_quiz_url = f"https://t.me/{bot_username}?start=quiz"
        
        keyboard = [
            [InlineKeyboardButton("🚀 Click here to start your quiz in private chat!", url=private_quiz_url)]
        ]
        markup = InlineKeyboardMarkup(keyboard)

        group_msg = (
            f"{BOT_BRANDING_HEADER}\n\n"
            f"📚 **New Practice Session Available!**\n\n"
            f"Hey {user.mention_markdown()}! To prevent screen clutter in the group, "
            f"click the button below to launch your personal, uninterrupted quiz in private chat:"
        )
        await update.message.reply_text(group_msg, reply_markup=markup, parse_mode="Markdown")
        return

    # PRIVATE CHAT QUIZ FLOW
    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}
    
    if not profile or not profile.get("is_verified"):
        await update.message.reply_text("⚠️ **Registration Required**\n\nPlease type /start first to create your profile before attempting quizzes!", parse_mode="Markdown")
        return

    attempted_today = get_today_attempts(user.id)
    if attempted_today >= DAILY_QUESTION_LIMIT:
        await update.message.reply_text(f"🛑 **Daily Target Reached!**\n\nYou have completed your limit of {DAILY_QUESTION_LIMIT} questions for today. Excellent effort! Resume practice tomorrow.", reply_markup=get_main_menu_keyboard())
        return

    keyboard = [
        [InlineKeyboardButton("10 Questions", callback_data="quiz_count_10"), InlineKeyboardButton("15 Questions", callback_data="quiz_count_15")],
        [InlineKeyboardButton("20 Questions", callback_data="quiz_count_20"), InlineKeyboardButton("25 Questions", callback_data="quiz_count_25")],
        [InlineKeyboardButton("30 Questions (Max)", callback_data="quiz_count_30")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"{BOT_BRANDING_HEADER}\n\n"
        f"📊 **Quiz Setup — Select Question Target (Step 1/2)**\n\n"
        f"Select the number of questions for this test session:\n"
        f"*(Remaining daily quota: `{DAILY_QUESTION_LIMIT - attempted_today}` / `{DAILY_QUESTION_LIMIT}`)*",
        reply_markup=markup,
        parse_mode="Markdown"
    )

async def quiz_count_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    count = int(query.data.replace("quiz_count_", ""))
    QUIZ_SETUP_CACHE[user_id] = {"count": count}
    
    keyboard = [
        [InlineKeyboardButton("⏱ 12 Seconds", callback_data="quiz_timer_12"), InlineKeyboardButton("⏱ 15 Seconds", callback_data="quiz_timer_15")],
        [InlineKeyboardButton("⏱ 18 Seconds", callback_data="quiz_timer_18"), InlineKeyboardButton("⏱ 20 Seconds", callback_data="quiz_timer_20")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"{BOT_BRANDING_HEADER}\n\n"
        f"⏱ **Quiz Setup — Select Timer (Step 2/2)**\n\n"
        f"Selected: `{count} Questions`\n\n"
        f"Choose timer duration per question:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

async def quiz_timer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    timer_sec = int(query.data.replace("quiz_timer_", ""))
    setup = QUIZ_SETUP_CACHE.pop(user_id, {"count": 20})
    count = setup.get("count", 20)
    
    session, msg = start_quiz_session(user_id, requested_count=count, timer_sec=timer_sec)
    
    if not session:
        await query.edit_message_text(f"🛑 {msg}")
        return

    await query.edit_message_text(
        f"{BOT_BRANDING_HEADER}\n\n"
        f"🚀 **Session Started!**\n\n"
        f"🎯 Target: `{session['total']} Questions`\n"
        f"⏱ Timer: `{timer_sec}s / Question`\n\n"
        f"Loading Question 1/{session['total']}...",
        parse_mode="Markdown"
    )
    await send_next_question(query.message.chat_id, user_id, context)

async def send_next_question(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    session = get_active_session(user_id)
    if not session or session.get("is_paused"):
        return

    if session["current_index"] >= session["total"]:
        await send_completion_banner(chat_id, user_id, context)
        return

    timer_sec = session.get("timer_sec", 15)
    if timer_sec < 10: 
        timer_sec = 10

    q = session["questions"][session["current_index"]]
    
    raw_question = q['question']
    header_text = f"🖥 [Q {session['current_index']+1}/{session['total']}]\n\n{raw_question}"
    if len(header_text) > 300:
        header_text = header_text[:297] + "..."

    clean_options = [str(opt)[:97] + "..." if len(str(opt)) > 100 else str(opt) for opt in q["options"]]

    explanation_text = q.get("explanation", "Keep practicing daily with Learn with HiM Quiz Book by Himanshu Sir!")
    if len(explanation_text) > 200:
        explanation_text = explanation_text[:197] + "..."

    correct_opt_id = q.get("correct_option", 0)
    if not isinstance(correct_opt_id, int) or correct_opt_id < 0 or correct_opt_id >= len(clean_options):
        correct_opt_id = 0

    try:
        poll_msg = await context.bot.send_poll(
            chat_id=chat_id,
            question=header_text,
            options=clean_options,
            type=Poll.QUIZ,
            correct_option_id=correct_opt_id,
            explanation=explanation_text,
            explanation_parse_mode="Markdown",
            is_anonymous=False,
            open_period=timer_sec
        )
        
        poll_id = poll_msg.poll.id
        session["active_poll_id"] = poll_id
        
        POLL_SESSION_MAP[poll_id] = {
            "user_id": user_id,
            "chat_id": chat_id,
            "q_index": session["current_index"],
            "correct_option": correct_opt_id
        }

        if user_id in TIMER_TASKS and not TIMER_TASKS[user_id].done():
            TIMER_TASKS[user_id].cancel()

        task = asyncio.create_task(auto_skip_timer(chat_id, user_id, poll_id, session["current_index"], timer_sec, context))
        TIMER_TASKS[user_id] = task

    except Exception as e:
        logging.error(f"⚠️ Telegram API rejected question #{session['current_index']+1}: {e}")
        session["skipped_count"] += 1
        session["current_index"] += 1
        await send_next_question(chat_id, user_id, context)

async def auto_skip_timer(chat_id: int, user_id: int, poll_id: str, expected_q_index: int, timer_sec: int, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(timer_sec + 1)
    
    if poll_id in POLL_SESSION_MAP:
        POLL_SESSION_MAP.pop(poll_id, None)
        session = get_active_session(user_id)
        
        if session and not session.get("is_paused") and session["current_index"] == expected_q_index:
            session["skipped_count"] += 1
            session["current_index"] += 1
            
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"⏱ **Time's Up! Question Skipped.**\nAdvancing to Question {session['current_index']+1}/{session['total']}...",
                parse_mode="Markdown"
            )
            await asyncio.sleep(1.0)
            await send_next_question(chat_id, user_id, context)

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    
    if poll_id not in POLL_SESSION_MAP:
        return

    poll_data = POLL_SESSION_MAP.pop(poll_id)
    user_id = poll_data["user_id"]
    chat_id = poll_data["chat_id"]
    
    if user_id in TIMER_TASKS and not TIMER_TASKS[user_id].done():
        TIMER_TASKS[user_id].cancel()

    session = get_active_session(user_id)
    if session and not session.get("is_paused") and session["current_index"] == poll_data["q_index"]:
        selected_option = answer.option_ids[0] if answer.option_ids else -1
        
        if selected_option == poll_data["correct_option"]:
            session["score"] += 1.0
            session["correct_count"] += 1
            
        session["current_index"] += 1
        await asyncio.sleep(1.0)
        await send_next_question(chat_id, user_id, context)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_active_session(user_id)
    
    if not session:
        await update.message.reply_text("⚠️ No active test session found to pause.", reply_markup=get_main_menu_keyboard())
        return

    session["is_paused"] = True
    if user_id in TIMER_TASKS and not TIMER_TASKS[user_id].done():
        TIMER_TASKS[user_id].cancel()

    await update.message.reply_text(
        f"⏸ **Test Session Paused**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Saved progress at Question `{session['current_index']+1} / {session['total']}`.\n\n"
        f"👉 Type /resume whenever you are ready to continue!",
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_active_session(user_id)
    
    if not session or not session.get("is_paused"):
        await update.message.reply_text("⚠️ No paused test found. Type /quiz to start a new mock test!", reply_markup=get_main_menu_keyboard())
        return

    session["is_paused"] = False
    await update.message.reply_text(
        f"▶️ **Resuming Test Session!**\n\n"
        f"Loading Question {session['current_index']+1}/{session['total']}...",
        parse_mode="Markdown"
    )
    await send_next_question(update.effective_chat.id, user_id, context)

async def send_completion_banner(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    session = finish_quiz_session(user_id)
    if not session:
        return

    score = max(0.0, session["score"])
    total = session["total"]
    accuracy = round((session["correct_count"] / total) * 100, 1) if total > 0 else 0

    clean_channel = CHANNEL_USERNAME.replace("@", "")
    
    keyboard = [
        [InlineKeyboardButton("🚀 /quiz", callback_data="quick_cmd_quiz"), InlineKeyboardButton("📊 /help", callback_data="quick_cmd_help")],
        [InlineKeyboardButton("🏆 /toppersname", callback_data="quick_cmd_toppers"), InlineKeyboardButton("🥇 /myrank", callback_data="quick_cmd_rank")],
        [InlineKeyboardButton("👤 /myprofile", callback_data="quick_cmd_profile"), InlineKeyboardButton("📈 /myperformance", callback_data="quick_cmd_perf")],
        [InlineKeyboardButton("🎓 /mywholestate", callback_data="quick_cmd_state")],
        [InlineKeyboardButton("📢 Join @LearnwithHiM Channel", url=f"https://t.me/{clean_channel}")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    banner = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"🏆 **Test Completed Successfully!**\n\n"
        f"🎖 **Total Score:** `{score} / {total}`\n"
        f"✅ **Correct Answers:** `{session['correct_count']} / {total}`\n"
        f"⏭ **Skipped Questions:** `{session['skipped_count']}`\n"
        f"🎯 **Accuracy Rate:** `{accuracy}%`\n\n"
        f"🌟 *Great job! Consistent daily practice with Himanshu Sir ensures top exam rank.* \n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **Tap any command button below to continue:**"
    )
    await context.bot.send_message(chat_id=chat_id, text=banner, reply_markup=markup, parse_mode="Markdown")

async def quick_command_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    chat_id = query.message.chat_id
    
    if data == "quick_cmd_quiz":
        class DummyUpdate:
            def __init__(self, uid, cid):
                self.effective_user = type('obj', (object,), {'id': uid, 'mention_markdown': lambda: query.from_user.mention_markdown()})
                self.effective_chat = type('obj', (object,), {'id': cid, 'type': query.message.chat.type})
                self.message = type('obj', (object,), {'chat_id': cid, 'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})
        fake_update = DummyUpdate(query.from_user.id, chat_id)
        await quiz_command(fake_update, context)

    elif data == "quick_cmd_hello":
        class DummyUpdate:
            def __init__(self, uid, cid):
                self.effective_user = type('obj', (object,), {'id': uid, 'full_name': query.from_user.full_name})
                self.message = type('obj', (object,), {'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})
        fake_update = DummyUpdate(query.from_user.id, chat_id)
        await hello_command(fake_update, context)

    elif data == "quick_cmd_help":
        class DummyUpdate:
            def __init__(self, uid, cid):
                self.effective_user = type('obj', (object,), {'id': uid, 'full_name': query.from_user.full_name})
                self.message = type('obj', (object,), {'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})
        fake_update = DummyUpdate(query.from_user.id, chat_id)
        await help_command(fake_update, context)

    elif data == "quick_cmd_toppers":
        class DummyUpdate:
            def __init__(self, cid):
                self.message = type('obj', (object,), {'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})
        fake_update = DummyUpdate(chat_id)
        await toppersname_handler(fake_update, context)

    elif data == "quick_cmd_rank":
        class DummyUpdate:
            def __init__(self, uid, cid):
                self.effective_user = type('obj', (object,), {'id': uid})
                self.message = type('obj', (object,), {'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})
        fake_update = DummyUpdate(query.from_user.id, chat_id)
        await myrank_handler(fake_update, context)

    elif data == "quick_cmd_profile":
        class DummyUpdate:
            def __init__(self, uid, cid):
                self.effective_user = type('obj', (object,), {'id': uid, 'full_name': query.from_user.full_name})
                self.message = type('obj', (object,), {'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})
        fake_update = DummyUpdate(query.from_user.id, chat_id)
        await myprofile_handler(fake_update, context)

    elif data == "quick_cmd_perf":
        class DummyUpdate:
            def __init__(self, uid, cid):
                self.effective_user = type('obj', (object,), {'id': uid})
                self.message = type('obj', (object,), {'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})
        fake_update = DummyUpdate(query.from_user.id, chat_id)
        await myperformance_handler(fake_update, context)

    elif data == "quick_cmd_state":
        class DummyUpdate:
            def __init__(self, uid, cid):
                self.effective_user = type('obj', (object,), {'id': uid, 'full_name': query.from_user.full_name})
                self.message = type('obj', (object,), {'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})
        fake_update = DummyUpdate(query.from_user.id, chat_id)
        await mywholestate_handler(fake_update, context)

# =====================================================================
#                      PUBLIC & ADMIN LEADERBOARD
# =====================================================================

async def toppersname_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    toppers = get_quiz_toppers(limit=10)
    if not toppers:
        await update.message.reply_text("🏆 No leaderboard records available yet. Complete a quiz to get listed!", reply_markup=get_main_menu_keyboard())
        return
        
    header = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"🏆 **Top 10 Leaderboard Scholars**\n\n"
    )
    lines = []
    for idx, t in enumerate(toppers, start=1):
        lines.append(f"{idx}. **{t['full_name']}** — Score: `{round(t['avg_score'], 2)}`")
        
    await update.message.reply_text(header + "\n".join(lines), reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Robust String Comparison for Admin Verification
    str_admin_ids = [str(aid).strip() for aid in ADMIN_IDS]
    if str(user_id).strip() not in str_admin_ids:
        await update.message.reply_text("🛑 **Access Denied:** Reserved for Himanshu Sir & System Administrators.", reply_markup=get_main_menu_keyboard())
        return

    toppers = get_quiz_toppers(limit=50)
    if not toppers:
        await update.message.reply_text("📊 No student records available in database yet.", reply_markup=get_main_menu_keyboard())
        return

    header = (
        f"🔐 **ADMIN MASTER DASHBOARD — ALL REGISTERED STUDENTS**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    lines = []
    for idx, t in enumerate(toppers, start=1):
        uid = t.get('user_id')
        raw_p = get_user_profile(uid)
        p = dict(raw_p) if raw_p else {}

        username_str = f"@{t['username']}" if t.get('username') and t.get('username') != 'N/A' else "No Username"
        phone = p.get('phone_number') or p.get('phone') or "N/A"
        age = p.get('age') or "N/A"
        gender = p.get('gender') or "N/A"
        target = p.get('target_exam') or t.get('target_exam') or "General"
        avg_score = round(t.get('avg_score', 0.0), 2)
        mocks_completed = p.get('total_mocks') or t.get('total_quizzes') or 0

        student_card = (
            f"👤 **Student #{idx}: {t.get('full_name')}** ({username_str})\n"
            f" └ **ID:** `{uid}`\n"
            f" └ **Target Exam:** `{target}`\n"
            f" └ **Age / Gender:** `{age}` / `{gender}`\n"
            f" └ **Phone:** `{phone}`\n"
            f" └ **Tests Completed:** `{mocks_completed}` | **Avg Score:** `{avg_score}`\n"
            f"───────────────────────────────"
        )
        lines.append(student_card)

    full_admin_report = header + "\n\n".join(lines)

    # Split output into chunked messages if character limit exceeds 4000
    if len(full_admin_report) > 4000:
        for chunk in [full_admin_report[i:i+3800] for i in range(0, len(full_admin_report), 3800)]:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        await update.message.reply_text("✅ End of Master Student Report.", reply_markup=get_main_menu_keyboard())
    else:
        await update.message.reply_text(full_admin_report, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

# =====================================================================
#                          STATISTICS & PROFILE
# =====================================================================

async def myprofile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}

    if not profile:
        await update.message.reply_text("Profile not found. Please type /start to create your profile.", reply_markup=get_main_menu_keyboard())
        return

    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"👤 **Student Profile Card**\n\n"
        f"• **Name:** {profile.get('full_name', user.full_name)}\n"
        f"• **Username:** @{profile.get('username') or 'N/A'}\n"
        f"• **Telegram ID:** `{profile.get('user_id', user.id)}`\n"
        f"• **Target Exam:** {profile.get('target_exam', 'General')}\n"
        f"• **Age:** {profile.get('age', 'N/A')}\n"
        f"• **Gender:** {profile.get('gender', 'N/A')}\n"
        f"• **Mobile Number:** `{profile.get('phone_number', 'N/A')}`\n"
        f"*(Mobile number hidden for privacy protection)*"
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def myrank_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rank = calculate_user_rank(user_id)
    await update.message.reply_text(f"🥇 **Your Global Leaderboard Rank:** #{rank}", reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def myperformance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    score_out_of_100, total_mocks = calculate_overall_performance(user_id)
    rating = "🌟 Excellent" if score_out_of_100 >= 80 else "👍 Good" if score_out_of_100 >= 50 else "⚠️ Needs Improvement"
    
    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"📊 **Performance Analytics**\n\n"
        f"• **Average Rating:** `{score_out_of_100} / 100`\n"
        f"• **Mock Tests Completed:** `{total_mocks}`\n"
        f"• **Performance Grade:** {rating}"
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def mywholestate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}

    if not profile:
        await update.message.reply_text("Profile not found. Please type /start to set up your profile.", reply_markup=get_main_menu_keyboard())
        return

    attempted_today = get_today_attempts(user.id)
    score_out_of_100, total_mocks = calculate_overall_performance(user.id)
    overall_rank = calculate_user_rank(user.id)
    
    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"🎓 **Student Progress Report**\n\n"
        f"👤 **Student Details:**\n"
        f"• **Name:** {profile.get('full_name', user.full_name)}\n"
        f"• **Target Exam:** {profile.get('target_exam', 'General')}\n"
        f"• **Age / Gender:** {profile.get('age', 'N/A')} / {profile.get('gender', 'N/A')}\n"
        f"• **User ID:** `{profile.get('user_id', user.id)}`\n\n"
        f"📈 **Academic Statistics:**\n"
        f"• **Overall Score:** `{score_out_of_100} / 100`\n"
        f"• **Global Rank:** #{overall_rank}\n"
        f"• **Tests Completed:** {total_mocks}\n\n"
        f"⏳ **Daily Practice Quota:**\n"
        f"• **Attempted Today:** {attempted_today} / {DAILY_QUESTION_LIMIT}\n"
        f"• **Remaining Today:** {max(0, DAILY_QUESTION_LIMIT - attempted_today)}\n\n"
        f"💡 Type /help to view all available commands."
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

# =====================================================================
#                          APPLICATION BUILDER
# =====================================================================

def build_application() -> Application:
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
    onboarding_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_onboarding)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_step)],
            TARGET_EXAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, target_exam_step)],
            PHONE_OTP: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), phone_otp_step)],
            AGE_STEP: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_step)],
            GENDER_STEP: [MessageHandler(filters.TEXT & ~filters.COMMAND, gender_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel_onboarding)],
        per_chat=True,
        per_user=True
    )
    app.add_handler(onboarding_handler)
    
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("hello", hello_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("toppersname", toppersname_handler))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("myprofile", myprofile_handler))
    app.add_handler(CommandHandler("myrank", myrank_handler))
    app.add_handler(CommandHandler("myperformance", myperformance_handler))
    app.add_handler(CommandHandler("mywholestate", mywholestate_handler))
    
    # Message handlers for text menu buttons (e.g. "/quiz 🚀")
    app.add_handler(MessageHandler(filters.Regex(r"^/quiz"), quiz_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/help"), help_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/hello"), hello_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/myprofile"), myprofile_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/myrank"), myrank_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/myperformance"), myperformance_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/mywholestate"), mywholestate_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/toppersname"), toppersname_handler))

    app.add_handler(CallbackQueryHandler(quiz_count_callback, pattern="^quiz_count_"))
    app.add_handler(CallbackQueryHandler(quiz_timer_callback, pattern="^quiz_timer_"))
    app.add_handler(CallbackQueryHandler(quick_command_callback, pattern="^quick_cmd_"))
    
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    
    return app