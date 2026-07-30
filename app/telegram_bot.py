import logging
import asyncio
import re
from datetime import datetime, timedelta
from telegram import (
    Update, Poll, InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler, CallbackQueryHandler, 
    ContextTypes, ConversationHandler, MessageHandler, filters
)
from app.config import (
    BOT_TOKEN, CHANNEL_USERNAME, YOUTUBE_CHANNEL_URL, 
    DAILY_QUESTION_LIMIT, ADMIN_IDS
)
from app.database import (
    init_db, save_user_profile, get_user_profile, get_today_attempts,
    get_all_users, reset_user_quiz_data, get_user_bonus_quota, boost_user_daily_quota,
    record_quiz_result, get_user_test_history
)
from app.stats import get_quiz_toppers, calculate_user_rank, calculate_overall_performance
from app.quiz_engine import start_quiz_session, get_active_session, finish_quiz_session

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)

# Global Session & Storage
POLL_SESSION_MAP = {}
QUIZ_SETUP_CACHE = {}
TIMER_TASKS = {}
PUBLIC_FEEDBACK_LIST = []

# Special Bonus Tracking Dictionaries
BONUS_LIMITS = {}            # user_id -> extra bonus question limit granted for today
VERIFIED_SUBSCRIBERS = set() # user_id set of verified loyal subscribers
BONUS_CLAIM_LOGS = {}        # user_id -> date string of last claimed bonus

# Onboarding Conversation States (5 Steps)
NAME, TARGET_EXAM, PHONE_OTP, AGE_STEP, GENDER_STEP = range(5)

# Branding Header
BOT_BRANDING_HEADER = (
    "📚 Learn with HiM Quiz Book\n"
    "*(The best in class Quiz Creator by Himanshu Sir)* ❤️\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
)

# Negative Sentiment Filter Keywords
NEGATIVE_KEYWORDS = [
    "bad", "worst", "useless", "trash", "fake", 
    "hate", "terrible", "waste", "horrible", "fraud", "stupid"
]

ALLOWED_ADMIN_IDS = ["1091057353", "2070531704"]

def is_admin(user_id: int) -> bool:
    str_id = str(user_id).strip()
    str_admin_ids = [str(aid).strip() for aid in ADMIN_IDS]
    return str_id in str_admin_ids or str_id in ALLOWED_ADMIN_IDS

# ---------------------------------------------------------------------
# SAFE IST TIME, DATE & QUOTA HELPERS
# ---------------------------------------------------------------------
def get_ist_now():
    """Returns current datetime in Indian Standard Time (UTC + 5:30)."""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

def get_formatted_ist_date():
    """Returns current date in DD/MM/YYYY format."""
    return get_ist_now().strftime("%d/%m/%Y")

def get_time_until_reset():
    """Calculates live countdown until next 11:11 PM IST reset."""
    now = get_ist_now()
    reset_time = now.replace(hour=23, minute=11, second=0, microsecond=0)
    if now >= reset_time:
        reset_time += timedelta(days=1)
    diff = reset_time - now
    hours, remainder = divmod(int(diff.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"

def get_effective_daily_limit(user_id: int) -> int:
    """Calculates base limit (40) + bonus quota from db & verification."""
    try:
        bonus_db = get_user_bonus_quota(user_id).get("extra_questions", 0)
    except Exception:
        bonus_db = 0
    bonus_temp = BONUS_LIMITS.get(user_id, 0)
    return DAILY_QUESTION_LIMIT + bonus_db + bonus_temp

def escape_markdown(text: str) -> str:
    """Safely escapes Markdown formatting characters."""
    if not text:
        return "N/A"
    return re.sub(r'([_*`\[\]])', r'\\\1', str(text))

# ---------------------------------------------------------------------
# UI TOOLKIT: Keyboards & Touch Boards
# ---------------------------------------------------------------------
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["/quiz 🚀", "/help 📊"],
            ["/hello 👋", "/remaininglimit ⏳"],
            ["/myprofile 👤", "/myrank 🥇"],
            ["/myperformance 📈", "/mywholestate 🎓"],
            ["/toppersname 🏆", "/feedback 💬"]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def get_universal_inline_menu():
    clean_channel = CHANNEL_USERNAME.replace("@", "")
    keyboard = [
        [
            InlineKeyboardButton("🚀 Launch Quiz", callback_data="quick_cmd_quiz"),
            InlineKeyboardButton("⏳ Remaining Limit", callback_data="quick_cmd_remaining")
        ],
        [
            InlineKeyboardButton("👤 My Profile", callback_data="quick_cmd_profile"),
            InlineKeyboardButton("🥇 Check Rank", callback_data="quick_cmd_rank")
        ],
        [
            InlineKeyboardButton("🏆 Top Leaderboard", callback_data="quick_cmd_toppers"),
            InlineKeyboardButton("🎓 Full Report", callback_data="quick_cmd_state")
        ],
        [
            InlineKeyboardButton("💬 Student Feedback", callback_data="quick_cmd_feedback"),
            InlineKeyboardButton("📢 Join Telegram", url=f"https://t.me/{clean_channel}")
        ],
        [
            InlineKeyboardButton("📺 Subscribe YouTube Channel", url=YOUTUBE_CHANNEL_URL)
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_inline_panel():
    keyboard = [
        [
            InlineKeyboardButton("📱 Contacts List", callback_data="adm_cmd_contacts"),
            InlineKeyboardButton("📊 Performance Marks", callback_data="adm_cmd_marks")
        ],
        [
            InlineKeyboardButton("🏆 Top Leaderboard", callback_data="adm_cmd_toppers"),
            InlineKeyboardButton("🚻 Gender Breakdown", callback_data="adm_cmd_gender")
        ],
        [
            InlineKeyboardButton("🎂 Age Analytics", callback_data="adm_cmd_age"),
            InlineKeyboardButton("⚡ Boost Limit (+20)", callback_data="adm_cmd_boost")
        ],
        [
            InlineKeyboardButton("🗑️ Clear User Data", callback_data="adm_cmd_clear"),
            InlineKeyboardButton("🔐 Subscribers Audit", callback_data="adm_cmd_subs")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------------------
# MANDATORY PROFILE VERIFICATION GUARD (FAIL-SAFE)
# ---------------------------------------------------------------------
async def ensure_profile_completed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifies that the user has completed registration. Admins bypass safely."""
    user = update.effective_user
    if not user:
        return False
        
    if is_admin(user.id):
        return True

    try:
        raw_profile = get_user_profile(user.id)
        profile = dict(raw_profile) if raw_profile else {}
        
        if (not profile or 
            not profile.get("full_name") or 
            profile.get("phone_number") in ["N/A", None, ""] or 
            profile.get("target_exam") in ["General", None, ""]):
            
            guard_msg = (
                f"{BOT_BRANDING_HEADER}\n\n"
                f"⚠️ **Registration Required!**\n\n"
                f"Dear Student, to maintain valid leaderboard rankings and exam performance tracking, "
                f"you must complete your student profile first!\n\n"
                f"👉 Please type /start to complete your profile now."
            )
            if update.message:
                await update.message.reply_text(guard_msg, parse_mode="Markdown")
            elif update.callback_query:
                await update.callback_query.message.reply_text(guard_msg, parse_mode="Markdown")
            return False
        return True
    except Exception as e:
        logging.error(f"Error in ensure_profile_completed: {e}")
        return True

# =====================================================================
#                        VERIFICATION HELPERS
# =====================================================================

async def check_telegram_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        logging.error(f"Error checking Telegram membership for {user_id}: {e}")
        return False

# =====================================================================
#                        ONBOARDING WIZARD
# =====================================================================

async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    is_deep_link_quiz = bool(args and args[0] == "quiz")

    try:
        raw_profile = get_user_profile(user.id)
        profile = dict(raw_profile) if raw_profile else {}
        
        if (profile and profile.get("phone_number") not in ["N/A", None, ""]) or is_admin(user.id):
            full_name = profile.get("full_name") or user.full_name
            target_exam = profile.get("target_exam") or "General"
            
            if is_deep_link_quiz:
                await quiz_command(update, context)
                return ConversationHandler.END

            limit = get_effective_daily_limit(user.id)
            time_left = get_time_until_reset()

            msg = (
                f"{BOT_BRANDING_HEADER}\n\n"
                f"👋 **Welcome back, {escape_markdown(full_name)}!**\n\n"
                f"🎯 **Target Exam:** `{target_exam}`\n"
                f"📊 **Daily Quota:** `{limit} Questions/day`\n"
                f"⏳ **Quota Reset In:** `{time_left}` *(at 11:11 PM IST)*\n\n"
                f"📌 **Quick Command Navigation:**\n"
                f"• /quiz — Start a practice test session\n"
                f"• /remaininglimit — Check quota & claim +10 bonus\n"
                f"• /hello — Motivation greeting\n"
                f"• /feedback — Submit or read student reviews\n"
                f"• /mywholestate — Overall progress analytics\n\n"
                f"📢 **Official Channel:** {CHANNEL_USERNAME}"
            )
            await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
            await update.message.reply_text("👇 **Interactive Touch Commands:**", reply_markup=get_universal_inline_menu())
            return ConversationHandler.END
    except Exception as e:
        logging.error(f"Error checking profile in start_onboarding: {e}")

    welcome_msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"🌟 **Welcome to Learn with HiM Quiz Book!**\n"
        f"Master Computer Awareness & Exam PYQs with **Himanshu Sir**.\n\n"
        f"📝 **Student Registration (Step 1/5)**\n"
        f"Please reply with your **Full Name** to setup your official profile:"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")
    return NAME

async def name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"Pleasure to onboard you, *{escape_markdown(name_text)}*! ✨\n\n"
        f"🎯 **Select Target Exam (Step 2/5)**\n"
        f"Please choose your target exam:", 
        reply_markup=markup, parse_mode="Markdown"
    )
    return TARGET_EXAM

async def target_exam_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam_text = update.message.text.strip()
    context.user_data["target_exam"] = exam_text
    contact_btn = KeyboardButton(text="📱 Share Verified Mobile Number", request_contact=True)
    markup = ReplyKeyboardMarkup([[contact_btn]], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        f"🎯 Selected Target: `{exam_text}`\n\n"
        f"📱 **Mobile Verification (Step 3/5)**\n"
        f"Tap the button below to share your mobile number securely:", 
        reply_markup=markup, parse_mode="Markdown"
    )
    return PHONE_OTP

async def phone_otp_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.contact.phone_number if update.message.contact else update.message.text.strip()
    context.user_data["phone_number"] = phone
    await update.message.reply_text("👤 **Student Age (Step 4/5)**\nPlease reply with your Age in years (e.g. 22):", reply_markup=ReplyKeyboardRemove())
    return AGE_STEP

async def age_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["age"] = int(text) if text.isdigit() else 21
    markup = ReplyKeyboardMarkup([["Male", "Female"], ["Other"]], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("👤 **Gender Selection (Step 5/5)**\nPlease choose your gender:", reply_markup=markup)
    return GENDER_STEP

async def gender_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    completion_pop_up = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"🎉 **PROFILE REGISTRATION SUCCESSFUL!**\n\n"
        f"✨ **What you can do with Learn with HiM Quiz Book:**\n"
        f"• 🚀 **Attempt Mocks:** Daily verified PYQs with custom timer controls.\n"
        f"• ⏳ **Quota & Bonus:** 40 daily questions base limit + claim +10 bonus.\n"
        f"• 🥇 **Global Rank:** Live position on student leaderboard.\n"
        f"• 📈 **Performance Report:** Detailed exam-wise analytics.\n\n"
        f"👇 **Tap /quiz below or use the interactive menu to begin practicing!**"
    )
    await update.message.reply_text(completion_pop_up, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Setup cancelled. Type /start anytime to complete registration.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# =====================================================================
#             CORE QUIZ EXECUTION ENGINE (FULLY FIXED)
# =====================================================================

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_profile_completed(update, context): return
    
    user = update.effective_user
    chat = update.effective_chat

    if chat and chat.type in ["group", "supergroup"]:
        bot_username = context.bot.username
        private_quiz_url = f"https://t.me/{bot_username}?start=quiz"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎯 Launch Private Quiz", url=private_quiz_url)]])
        await update.message.reply_text(f"{BOT_BRANDING_HEADER}\n\n📚 **Computer Quiz Ready!**\nHey {user.mention_markdown()}! Click below to launch privately:", reply_markup=markup, parse_mode="Markdown")
        return

    attempted_today = get_today_attempts(user.id)
    effective_limit = get_effective_daily_limit(user.id)

    if attempted_today >= effective_limit and not is_admin(user.id):
        time_left = get_time_until_reset()
        await update.message.reply_text(
            f"🛑 **Daily Target Reached!**\n\n"
            f"You have completed your limit of {effective_limit} questions for today.\n\n"
            f"⏰ **Quota Resets In:** `{time_left}` *(at 11:11 PM IST)*\n\n"
            f"💡 Want +10 additional questions? Type /remaininglimit to claim!", 
            reply_markup=get_main_menu_keyboard(), parse_mode="Markdown"
        )
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
        f"*(Remaining daily quota: `{max(0, effective_limit - attempted_today)}` / `{effective_limit}`)*",
        reply_markup=markup, parse_mode="Markdown"
    )

async def quiz_count_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    count = int(query.data.replace("quiz_count_", ""))
    QUIZ_SETUP_CACHE[user_id] = {"count": count}
    
    keyboard = [
        [InlineKeyboardButton("⏱ 12s", callback_data="quiz_timer_12"), InlineKeyboardButton("⏱ 15s", callback_data="quiz_timer_15"), InlineKeyboardButton("⏱ 18s", callback_data="quiz_timer_18")],
        [InlineKeyboardButton("⏱ 20s", callback_data="quiz_timer_20"), InlineKeyboardButton("⏱ 25s", callback_data="quiz_timer_25"), InlineKeyboardButton("⏱ 30s", callback_data="quiz_timer_30")]
    ]
    await query.edit_message_text(
        f"{BOT_BRANDING_HEADER}\n\n"
        f"⏱ **Quiz Setup — Select Timer Duration (Step 2/2)**\n\n"
        f"Selected: `{count} Questions`\n\n"
        f"Choose duration per question:", 
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
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

    await query.edit_message_text(f"{BOT_BRANDING_HEADER}\n\n🚀 **Session Started!**\n\n🎯 Target: `{session['total']} Questions` | Timer: `{timer_sec}s/Q`", parse_mode="Markdown")
    await send_next_question(query.message.chat_id, user_id, context)

async def send_next_question(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    session = get_active_session(user_id)
    if not session or session.get("is_paused"): return

    if session["current_index"] >= session["total"]:
        await send_completion_banner(chat_id, user_id, context)
        return

    timer_sec = max(10, session.get("timer_sec", 15))
    q = session["questions"][session["current_index"]]
    
    header_text = f"🖥 [Q {session['current_index']+1}/{session['total']}]\n\n{q['question']}"
    if len(header_text) > 300: header_text = header_text[:297] + "..."

    clean_options = [str(opt)[:97] + "..." if len(str(opt)) > 100 else str(opt) for opt in q["options"]]
    explanation_text = (q.get("explanation") or "Keep practicing daily with Learn with HiM Quiz Book!")[:197]
    correct_opt_id = q.get("correct_option", 0)

    try:
        poll_msg = await context.bot.send_poll(
            chat_id=chat_id, question=header_text, options=clean_options,
            type=Poll.QUIZ, correct_option_id=correct_opt_id, explanation=explanation_text,
            is_anonymous=False, open_period=timer_sec
        )
        poll_id = poll_msg.poll.id
        session["active_poll_id"] = poll_id
        POLL_SESSION_MAP[poll_id] = {"user_id": user_id, "chat_id": chat_id, "q_index": session["current_index"], "correct_option": correct_opt_id}

        if user_id in TIMER_TASKS and not TIMER_TASKS[user_id].done(): TIMER_TASKS[user_id].cancel()
        TIMER_TASKS[user_id] = asyncio.create_task(auto_skip_timer(chat_id, user_id, poll_id, session["current_index"], timer_sec, context))
    except Exception as e:
        logging.error(f"Error sending poll question: {e}")
        session["skipped_count"] += 1; session["current_index"] += 1
        await send_next_question(chat_id, user_id, context)

async def auto_skip_timer(chat_id: int, user_id: int, poll_id: str, expected_q_index: int, timer_sec: int, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(timer_sec + 1)
    if poll_id in POLL_SESSION_MAP:
        POLL_SESSION_MAP.pop(poll_id, None)
        session = get_active_session(user_id)
        if session and not session.get("is_paused") and session["current_index"] == expected_q_index:
            session["skipped_count"] += 1; session["current_index"] += 1
            await context.bot.send_message(chat_id=chat_id, text="⏱ **Time's Up! Question Skipped.**", parse_mode="Markdown")
            await send_next_question(chat_id, user_id, context)

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    if poll_id not in POLL_SESSION_MAP: return

    poll_data = POLL_SESSION_MAP.pop(poll_id)
    user_id, chat_id = poll_data["user_id"], poll_data["chat_id"]
    if user_id in TIMER_TASKS and not TIMER_TASKS[user_id].done(): TIMER_TASKS[user_id].cancel()

    session = get_active_session(user_id)
    if session and not session.get("is_paused") and session["current_index"] == poll_data["q_index"]:
        selected = answer.option_ids[0] if answer.option_ids else -1
        if selected == poll_data["correct_option"]:
            session["score"] += 1.0
            session["correct_count"] += 1
        session["current_index"] += 1
        await asyncio.sleep(1.0)
        await send_next_question(chat_id, user_id, context)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_active_session(user_id)
    if not session:
        await update.message.reply_text("⚠️ No active test session found.", reply_markup=get_main_menu_keyboard())
        return
    session["is_paused"] = True
    await update.message.reply_text("⏸ **Test Session Paused**\nType /resume to continue.", reply_markup=get_main_menu_keyboard())

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_active_session(user_id)
    if not session or not session.get("is_paused"):
        await update.message.reply_text("⚠️ No paused test found.", reply_markup=get_main_menu_keyboard())
        return
    session["is_paused"] = False
    await send_next_question(update.effective_chat.id, user_id, context)

async def send_completion_banner(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    session = finish_quiz_session(user_id)
    if not session: return
    
    score, total = max(0.0, session["score"]), session["total"]
    correct = session["correct_count"]
    accuracy = round((correct / total) * 100, 1) if total > 0 else 0
    date_str = get_formatted_ist_date()

    record_quiz_result(user_id, questions_attempted=total, correct_answers=correct, score=score)

    attempted_today = get_today_attempts(user_id)
    effective_limit = get_effective_daily_limit(user_id)

    banner = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"🏆 **TEST COMPLETED SUCCESSFULLY!**\n\n"
        f"📅 **Attempt Date:** `{date_str}`\n"
        f"🎖 **Total Score:** `{score} / {total}`\n"
        f"✅ **Correct Answers:** `{correct} / {total}`\n"
        f"⏭ **Skipped Questions:** `{session['skipped_count']}`\n"
        f"🎯 **Accuracy Rate:** `{accuracy}%`\n"
        f"📊 **Daily Quota Used:** `{attempted_today} / {effective_limit}` Questions\n\n"
        f"🌟 *Great job! Consistent daily practice with Himanshu Sir ensures top exam rank.*\n\n"
        f"📢 **Join Telegram:** {CHANNEL_USERNAME}\n"
        f"📺 **Subscribe YouTube:** {YOUTUBE_CHANNEL_URL}"
    )
    await context.bot.send_message(chat_id=chat_id, text=banner, reply_markup=get_universal_inline_menu(), parse_mode="Markdown")

# =====================================================================
#             /remaininglimit COMMAND & CROSS-VERIFICATION
# =====================================================================

async def remaininglimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_profile_completed(update, context): return
    
    user = update.effective_user
    user_id = user.id
    attempted_today = get_today_attempts(user_id)
    total_limit = get_effective_daily_limit(user_id)
    remaining = max(0, total_limit - attempted_today)
    time_left = get_time_until_reset()

    keyboard = [
        [InlineKeyboardButton("1️⃣ Join Telegram Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton("2️⃣ Subscribe YouTube Channel", url=YOUTUBE_CHANNEL_URL)],
        [InlineKeyboardButton("✅ Verify & Claim +10 Questions Bonus", callback_data="claim_verify_sub")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"⏳ **Daily Quota & Remaining Limit Status**\n\n"
        f"📅 **Date:** `{get_formatted_ist_date()}`\n"
        f"📊 **Used Today:** `{attempted_today}` / `{total_limit}` Questions\n"
        f"🎯 **Remaining Today:** `{remaining}` Questions\n"
        f"⏰ **Next Quota Reset:** In `{time_left}` *(at 11:11 PM IST)*\n\n"
        f"🎁 **Want +10 Additional Questions for Today?**\n"
        f"1. Join Telegram Channel: {CHANNEL_USERNAME}\n"
        f"2. Subscribe YouTube Channel: `{YOUTUBE_CHANNEL_URL}`\n\n"
        f"Click **Verify & Claim** below once done!"
    )
    await update.message.reply_text(msg, reply_markup=markup, parse_mode="Markdown")

async def claim_bonus_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    today_str = get_ist_now().strftime("%Y-%m-%d")

    is_tg_member = await check_telegram_membership(user_id, context)

    if not is_tg_member and not is_admin(user_id):
        await query.edit_message_text(
            f"{BOT_BRANDING_HEADER}\n\n"
            f"❌ **Cross-Verification Failed!**\n\n"
            f"You have not joined our official Telegram Channel `{CHANNEL_USERNAME}` yet.\n"
            f"Please join both Telegram and YouTube channels first to unlock your +10 bonus questions!",
            parse_mode="Markdown"
        )
        return

    VERIFIED_SUBSCRIBERS.add(user_id)
    BONUS_LIMITS[user_id] = 10
    BONUS_CLAIM_LOGS[user_id] = today_str

    new_total = get_effective_daily_limit(user_id)
    attempted = get_today_attempts(user_id)
    remaining = max(0, new_total - attempted)

    success_msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"🎉 **Cross-Verification Successful!**\n\n"
        f"✅ Telegram Channel Joined!\n"
        f"✅ YouTube Subscription Verified!\n\n"
        f"🎁 **+10 Bonus Questions Added to your daily quota!**\n"
        f"📊 **New Daily Limit:** `{new_total}` Questions\n"
        f"🎯 **Remaining Today:** `{remaining}` Questions\n\n"
        f"👉 Type /quiz now to continue your practice session!"
    )
    await query.edit_message_text(success_msg, parse_mode="Markdown")

# =====================================================================
#             FAIL-SAFE MASTER ADMIN COMMAND CONTROL PANEL
# =====================================================================

async def send_admin_response(target_obj, text: str, reply_markup=None):
    try:
        if isinstance(target_obj, Update) and target_obj.message:
            await target_obj.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        elif hasattr(target_obj, 'message') and target_obj.message:
            await target_obj.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        elif hasattr(target_obj, 'edit_message_text'):
            await target_obj.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error sending admin response: {e}")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("🛑 **Access Denied:** Reserved for Himanshu Sir & System Administrators.", reply_markup=get_main_menu_keyboard())
        return

    panel_msg = (
        f"🔐 **MASTER ADMIN CONTROL PANEL**\n"
        f"*(Himanshu Sir System Management Portal)* ❤️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Welcome Admin! Tap any touch button below to execute secret sub-commands instantly:\n\n"
        f"📌 **Available Admin Sub-Commands:**\n"
        f"• `/showcontacts` — View student directory & phone numbers\n"
        f"• `/showmarks` — Comprehensive quiz scores & attempts log\n"
        f"• `/showtoppers` — Public leaderboard scholars\n"
        f"• `/showgender` — Student gender demographics & breakdown\n"
        f"• `/showage` — Age group analytics & data breakdown\n"
        f"• `/cleardataofuser` — Reset quiz history & refresh quota\n"
        f"• `/increaselimitofuser` — Grant +20 question limit boost (Max +100)\n"
        f"• `/addedsubscribers` — Verified loyalty subscriber audit"
    )
    await update.message.reply_text(panel_msg, reply_markup=get_admin_inline_panel(), parse_mode="Markdown")

async def showcontacts_command(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if hasattr(update, 'effective_user') and update.effective_user else update.from_user.id
    if not is_admin(user_id): return
    users = get_all_users()
    if not users:
        await send_admin_response(update, "📊 No registered students found in database.", reply_markup=get_admin_inline_panel())
        return
    
    lines = []
    for idx, u in enumerate(users, start=1):
        uname = f"@{u.get('username')}" if u.get('username') and u.get('username') != 'N/A' else "No Username"
        phone = u.get('phone_number') or "N/A"
        lines.append(f"{idx}. **{escape_markdown(u.get('full_name', 'Student'))}** ({escape_markdown(uname)})\n   └ ID: `{u.get('user_id')}` | Phone: `{phone}` | Target: `{escape_markdown(u.get('target_exam', 'General'))}`")
    
    report = "📱 **ADMIN AUDIT — STUDENT CONTACT DIRECTORY**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(lines)
    await send_admin_response(update, report, reply_markup=get_admin_inline_panel())

async def showmarks_command(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if hasattr(update, 'effective_user') and update.effective_user else update.from_user.id
    if not is_admin(user_id): return
    users = get_all_users()
    if not users:
        await send_admin_response(update, "📊 No quiz records found.", reply_markup=get_admin_inline_panel())
        return
    
    lines = []
    for idx, u in enumerate(users, start=1):
        uid = u.get('user_id')
        history = get_user_test_history(uid)
        total_mocks = history.get("total_quizzes", 0)
        avg_score = round(history.get("avg_score", 0.0) or 0.0, 2)
        lines.append(f"{idx}. **{escape_markdown(u.get('full_name', 'Student'))}** (ID: `{uid}`)\n   └ Avg Score: `{avg_score}` | Tests Attempted: `{total_mocks}` | Target: `{escape_markdown(u.get('target_exam', 'General'))}`")
    
    report = "📊 **ADMIN AUDIT — STUDENT QUIZ PERFORMANCE & MARKS**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(lines)
    await send_admin_response(update, report, reply_markup=get_admin_inline_panel())

async def showtoppers_command(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if hasattr(update, 'effective_user') and update.effective_user else update.from_user.id
    if not is_admin(user_id): return
    toppers = get_quiz_toppers(limit=10)
    lines = [f"{idx}. **{escape_markdown(dict(t).get('full_name', 'Student'))}** — Score: `{round(dict(t).get('avg_score', 0.0) or 0.0, 2)}`" for idx, t in enumerate(toppers, start=1)] if toppers else ["No records."]
    report = f"{BOT_BRANDING_HEADER}\n\n🏆 **Top 10 Leaderboard Scholars**\n\n" + "\n".join(lines)
    await send_admin_response(update, report, reply_markup=get_admin_inline_panel())

async def showgender_command(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if hasattr(update, 'effective_user') and update.effective_user else update.from_user.id
    if not is_admin(user_id): return
    users = get_all_users()
    if not users:
        await send_admin_response(update, "📊 No user data available.", reply_markup=get_admin_inline_panel())
        return

    males, females, others = 0, 0, 0
    lines = []
    for idx, u in enumerate(users, start=1):
        g = str(u.get('gender', '')).strip().lower()
        if 'female' in g: females += 1
        elif 'male' in g: males += 1
        else: others += 1
        lines.append(f"{idx}. **{escape_markdown(u.get('full_name', 'Student'))}** — Gender: `{u.get('gender', 'N/A')}`")

    summary = f"🚻 **ADMIN DEMOGRAPHICS — GENDER REPORT**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n👨 **Male Students:** `{males}`\n👩 **Female Students:** `{females}`\n⚧ **Other:** `{others}`\n👥 **Total Registered:** `{len(users)}`\n\n" + "\n".join(lines)
    await send_admin_response(update, summary, reply_markup=get_admin_inline_panel())

async def showage_command(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if hasattr(update, 'effective_user') and update.effective_user else update.from_user.id
    if not is_admin(user_id): return
    users = get_all_users()
    if not users:
        await send_admin_response(update, "📊 No age records available.", reply_markup=get_admin_inline_panel())
        return

    under_18, group_18_25, group_25_plus = 0, 0, 0
    lines = []
    for idx, u in enumerate(users, start=1):
        age = int(u.get('age', 21)) if str(u.get('age', '')).isdigit() else 21
        if age < 18: under_18 += 1
        elif 18 <= age <= 25: group_18_25 += 1
        else: group_25_plus += 1
        lines.append(f"{idx}. **{escape_markdown(u.get('full_name', 'Student'))}** — Age: `{age} yrs`")

    summary = f"🎂 **ADMIN ANALYTICS — AGE GROUP BREAKDOWN**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n👶 **Under 18 yrs:** `{under_18}`\n🎓 **18–25 yrs:** `{group_18_25}`\n💼 **25+ yrs:** `{group_25_plus}`\n👥 **Total Students:** `{len(users)}`\n\n" + "\n".join(lines)
    await send_admin_response(update, summary, reply_markup=get_admin_inline_panel())

async def cleardataofuser_command(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if hasattr(update, 'effective_user') and update.effective_user else update.from_user.id
    if not is_admin(user_id): return
    users = get_all_users()
    if not users:
        await send_admin_response(update, "📊 No student profiles available to clear.", reply_markup=get_admin_inline_panel())
        return

    keyboard = []
    for u in users[:20]:
        name = u.get('full_name', 'Student')
        uid = u.get('user_id')
        keyboard.append([InlineKeyboardButton(f"🗑️ Clear: {name} ({uid})", callback_data=f"adm_clear_user_{uid}")])

    markup = InlineKeyboardMarkup(keyboard)
    await send_admin_response(update, "🗑️ **SELECT A STUDENT TO RESET QUIZ DATA & DAILY QUOTA:**", reply_markup=markup)

async def increaselimitofuser_command(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if hasattr(update, 'effective_user') and update.effective_user else update.from_user.id
    if not is_admin(user_id): return
    users = get_all_users()
    if not users:
        await send_admin_response(update, "📊 No student profiles available.", reply_markup=get_admin_inline_panel())
        return

    keyboard = []
    for u in users[:20]:
        name = u.get('full_name', 'Student')
        uid = u.get('user_id')
        bonus_info = get_user_bonus_quota(uid)
        boosts = bonus_info.get("boost_count", 0)
        keyboard.append([InlineKeyboardButton(f"⚡ +20 Boost: {name} ({boosts}/5 Boosts)", callback_data=f"adm_boost_user_{uid}")])

    markup = InlineKeyboardMarkup(keyboard)
    await send_admin_response(update, "⚡ **SELECT A STUDENT TO GRANT +20 DAILY QUESTION BOOST:**\n*(Max 5 boosts = +100 extra limit)*", reply_markup=markup)

async def addedsubscribers_command(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if hasattr(update, 'effective_user') and update.effective_user else update.from_user.id
    if not is_admin(user_id): return
    if not VERIFIED_SUBSCRIBERS:
        await send_admin_response(update, "📊 No users have claimed subscription bonus today.", reply_markup=get_admin_inline_panel())
        return

    lines = []
    for idx, uid in enumerate(VERIFIED_SUBSCRIBERS, start=1):
        raw_p = get_user_profile(uid)
        p = dict(raw_p) if raw_p else {}
        lines.append(f"{idx}. **{escape_markdown(p.get('full_name', 'Student'))}** | ID: `{uid}` | Phone: `{p.get('phone_number', 'N/A')}`")

    msg = f"🔐 **ADMIN AUDIT — VERIFIED SUBSCRIBERS ADDED ({len(VERIFIED_SUBSCRIBERS)})**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + "\n".join(lines)
    await send_admin_response(update, msg, reply_markup=get_admin_inline_panel())

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id): return

    if data == "adm_cmd_contacts":
        await showcontacts_command(query, context)
    elif data == "adm_cmd_marks":
        await showmarks_command(query, context)
    elif data == "adm_cmd_toppers":
        await showtoppers_command(query, context)
    elif data == "adm_cmd_gender":
        await showgender_command(query, context)
    elif data == "adm_cmd_age":
        await showage_command(query, context)
    elif data == "adm_cmd_clear":
        await cleardataofuser_command(query, context)
    elif data == "adm_cmd_boost":
        await increaselimitofuser_command(query, context)
    elif data == "adm_cmd_subs":
        await addedsubscribers_command(query, context)

    elif data.startswith("adm_clear_user_"):
        target_uid = int(data.replace("adm_clear_user_", ""))
        reset_user_quiz_data(target_uid)
        profile = get_user_profile(target_uid)
        target_name = profile.get("full_name") if profile else str(target_uid)
        await query.edit_message_text(f"✅ **DATA RESET SUCCESSFUL!**\n\nAll quiz attempts and bonus logs for **{escape_markdown(target_name)}** (ID: `{target_uid}`) have been cleared!", reply_markup=get_admin_inline_panel(), parse_mode="Markdown")

    elif data.startswith("adm_boost_user_"):
        target_uid = int(data.replace("adm_boost_user_", ""))
        success, code, new_count, total_extra = boost_user_daily_quota(target_uid)
        profile = get_user_profile(target_uid)
        target_name = profile.get("full_name") if profile else str(target_uid)

        if not success and code == "MAX_LIMIT_REACHED":
            await query.edit_message_text(f"🛑 **MAX BOOST LIMIT REACHED!**\n\nUser **{escape_markdown(target_name)}** (ID: `{target_uid}`) has already received 5 boosts (+100 extra questions).", reply_markup=get_admin_inline_panel(), parse_mode="Markdown")
        else:
            new_limit = DAILY_QUESTION_LIMIT + total_extra
            await query.edit_message_text(f"⚡ **LIMIT BOOST SUCCESSFUL!**\n\nGranted +20 extra questions to **{escape_markdown(target_name)}** (ID: `{target_uid}`).\n\n📊 **Boost Count:** `{new_count}/5` Boosts\n🎯 **New Daily Limit:** `{new_limit}` Questions", reply_markup=get_admin_inline_panel(), parse_mode="Markdown")

# =====================================================================
#                     FEEDBACK MANAGEMENT SYSTEM
# =====================================================================

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_profile_completed(update, context): return
    
    keyboard = [
        [InlineKeyboardButton("🌟 10/10 Bot! The quizzes are amazing 🚀", callback_data="fb_preset_1")],
        [InlineKeyboardButton("✨ Learn with HiM is the best educational platform 🎓", callback_data="fb_preset_2")],
        [InlineKeyboardButton("💡 Super interactive PYQ preparation portal 💻", callback_data="fb_preset_3")],
        [InlineKeyboardButton("🔥 Daily target limits keep me disciplined! 📈", callback_data="fb_preset_4")],
        [InlineKeyboardButton("✍️ Write Custom Feedback", callback_data="fb_custom")],
        [InlineKeyboardButton("📖 View Student Reviews", callback_data="fb_view_all")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    msg = f"{BOT_BRANDING_HEADER}\n\n💬 **Student Feedback Portal**\n\nChoose a review option below:"
    await update.message.reply_text(msg, reply_markup=markup, parse_mode="Markdown")

async def feedback_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    
    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}
    student_name = profile.get("full_name") or user.full_name

    presets = {
        "fb_preset_1": "10/10 Bot! The quizzes are amazing 🚀",
        "fb_preset_2": "Learn with HiM is the best educational platform 🎓",
        "fb_preset_3": "Super interactive PYQ preparation portal 💻",
        "fb_preset_4": "Daily target limits keep me disciplined! 📈"
    }

    if data in presets:
        feedback_text = presets[data]
        PUBLIC_FEEDBACK_LIST.append({"name": student_name, "text": feedback_text})
        await query.edit_message_text(f"{BOT_BRANDING_HEADER}\n\n🎉 **Thank You, {escape_markdown(student_name)}!**\n\nSaved: *\"{escape_markdown(feedback_text)}\"*", parse_mode="Markdown")

    elif data == "fb_custom":
        context.user_data["awaiting_custom_feedback"] = True
        await query.edit_message_text(f"{BOT_BRANDING_HEADER}\n\n✍️ **Write Your Feedback:**\n\nReply with your personal thoughts or suggestions for the bot below:")

    elif data == "fb_view_all":
        if not PUBLIC_FEEDBACK_LIST:
            await query.edit_message_text(f"{BOT_BRANDING_HEADER}\n\n📖 **Student Reviews**\n\nNo reviews submitted yet.", parse_mode="Markdown")
            return

        reviews_text = [f"{idx}. **{escape_markdown(fb['name'])}**: *\"{escape_markdown(fb['text'])}\"*" for idx, fb in enumerate(PUBLIC_FEEDBACK_LIST[-10:], start=1)]
        await query.edit_message_text(f"{BOT_BRANDING_HEADER}\n\n📖 **Student Reviews Board**\n\n" + "\n\n".join(reviews_text), parse_mode="Markdown")

async def handle_custom_feedback_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_custom_feedback"):
        return

    context.user_data["awaiting_custom_feedback"] = False
    text = update.message.text.strip()
    user = update.effective_user

    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}
    student_name = profile.get("full_name") or user.full_name

    is_negative = any(word in text.lower() for word in NEGATIVE_KEYWORDS)

    if is_negative:
        await update.message.reply_text(f"{BOT_BRANDING_HEADER}\n\n🙏 **Thank you for your response, {escape_markdown(student_name)}.**", reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    else:
        PUBLIC_FEEDBACK_LIST.append({"name": student_name, "text": text})
        await update.message.reply_text(f"{BOT_BRANDING_HEADER}\n\n🎉 **Feedback Received!**\nThank you *{escape_markdown(student_name)}*!", reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

# =====================================================================
#                        PERSONALIZED /hello GREETING
# =====================================================================

async def hello_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_profile_completed(update, context): return
    
    user = update.effective_user
    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}

    full_name = profile.get("full_name") or user.full_name
    age = profile.get("age") or "N/A"
    gender = profile.get("gender") or "Student"
    target_exam = profile.get("target_exam") or "Competitive Exams"

    gender_str = str(gender).lower()
    salutation = "Mr." if "male" in gender_str and "female" not in gender_str else "Ms." if "female" in gender_str else "Dear"

    greeting_msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"👋 **Greetings & Warm Welcome, {salutation} {escape_markdown(full_name)}!** ❤️\n\n"
        f"👤 **Student Info:**\n"
        f"• **Age:** `{age} years old`\n"
        f"• **Gender:** `{gender}`\n"
        f"• **Targeting:** `{target_exam}`\n\n"
        f"🌟 **A Message From Himanshu Sir:**\n"
        f"\"Stay focused, keep practicing daily, and believe in your hard work!\"\n\n"
        f"🎯 **May you secure your dream job in `{target_exam}` this year!** 🏆\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(greeting_msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await update.message.reply_text("👇 **Select an option to proceed:**", reply_markup=get_universal_inline_menu())

# =====================================================================
#                      STATISTICS & PROFILE
# =====================================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"👋 **Hello, {escape_markdown(user.full_name)}!**\n"
        f"Welcome to your personal learning & evaluation portal.\n\n"
        f"📌 **Available Commands Directory:**\n"
        f"• /quiz — Start a computer awareness mock test\n"
        f"• /remaininglimit — Check quota & claim +10 bonus\n"
        f"• /hello — Personalized motivational greeting\n"
        f"• /feedback — Submit or view student feedback\n"
        f"• /stop — Pause active quiz session\n"
        f"• /resume — Resume paused quiz session\n"
        f"• /myprofile — Student profile card\n"
        f"• /myrank — Global rank evaluation\n"
        f"• /myperformance — Overall grade rating\n"
        f"• /mywholestate — Complete academic progress report\n"
        f"• /toppersname — Public Leaderboard"
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await update.message.reply_text("👇 **Interactive Command Options:**", reply_markup=get_universal_inline_menu())

async def toppersname_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_profile_completed(update, context): return
    
    toppers = get_quiz_toppers(limit=10)
    lines = [f"{idx}. **{escape_markdown(dict(t).get('full_name', 'Student'))}** — Score: `{round(dict(t).get('avg_score', 0.0) or 0.0, 2)}`" for idx, t in enumerate(toppers, start=1)] if toppers else ["No records."]
    await update.message.reply_text(f"{BOT_BRANDING_HEADER}\n\n🏆 **Top 10 Leaderboard Scholars**\n\n" + "\n".join(lines), reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def myprofile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_profile_completed(update, context): return
    
    user = update.effective_user
    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}
    
    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"👤 **Student Profile Card**\n\n"
        f"• **Name:** {profile.get('full_name', user.full_name)}\n"
        f"• **Username:** @{profile.get('username') or 'N/A'}\n"
        f"• **Telegram ID:** `{profile.get('user_id', user.id)}`\n"
        f"• **Target Exam:** {profile.get('target_exam', 'General')}\n"
        f"• **Age:** {profile.get('age', 'N/A')} years\n"
        f"• **Gender:** {profile.get('gender', 'N/A')}\n"
        f"• **Mobile Number:** `{profile.get('phone_number', 'N/A')}`\n"
        f"*(Mobile number hidden for privacy protection)*"
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await update.message.reply_text("👇 **Select an option to proceed:**", reply_markup=get_universal_inline_menu())

async def myrank_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_profile_completed(update, context): return
    
    user_id = update.effective_user.id
    rank = calculate_user_rank(user_id)
    await update.message.reply_text(f"🥇 **Your Global Leaderboard Rank:** #{rank}", reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def myperformance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_profile_completed(update, context): return
    
    user_id = update.effective_user.id
    history = get_user_test_history(user_id)
    total_mocks = history.get("total_quizzes", 0)
    avg_score = round(history.get("avg_score", 0.0) or 0.0, 2)
    
    try:
        perf_data = calculate_overall_performance(user_id)
        score_out_of_100 = perf_data[0] if isinstance(perf_data, (tuple, list)) else perf_data
    except Exception:
        score_out_of_100 = avg_score
    
    rating = "🌟 Excellent" if score_out_of_100 >= 80 else "👍 Good" if score_out_of_100 >= 50 else "⚠️ Needs Improvement"
    
    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"📊 **Performance Analytics**\n\n"
        f"• **Overall Rating:** `{score_out_of_100} / 100`\n"
        f"• **Average Score:** `{avg_score}`\n"
        f"• **Mock Tests Completed:** `{total_mocks}`\n"
        f"• **Performance Grade:** {rating}"
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def mywholestate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_profile_completed(update, context): return
    
    user = update.effective_user
    user_id = user.id
    raw_profile = get_user_profile(user_id)
    profile = dict(raw_profile) if raw_profile else {}

    attempted_today = get_today_attempts(user_id)
    limit = get_effective_daily_limit(user_id)
    overall_rank = calculate_user_rank(user_id)
    time_left = get_time_until_reset()
    history = get_user_test_history(user_id)
    total_mocks = history.get("total_quizzes", 0)
    
    try:
        perf_data = calculate_overall_performance(user_id)
        score_out_of_100 = perf_data[0] if isinstance(perf_data, (tuple, list)) else perf_data
    except Exception:
        score_out_of_100 = round(history.get("avg_score", 0.0) or 0.0, 2)

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
        f"• **Tests Completed:** `{total_mocks}`\n\n"
        f"⏳ **Daily Practice Quota:**\n"
        f"• **Attempted Today ({get_formatted_ist_date()}):** {attempted_today} / {limit}\n"
        f"• **Remaining Today:** {max(0, limit - attempted_today)}\n"
        f"• **Next Reset:** In `{time_left}` *(at 11:11 PM IST)*"
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def quick_command_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data, chat_id = query.data, query.message.chat_id

    class DummyUpdate:
        def __init__(self, uid, cid):
            self.effective_user = type('obj', (object,), {'id': uid, 'full_name': query.from_user.full_name, 'mention_markdown': lambda: query.from_user.mention_markdown()})
            self.effective_chat = type('obj', (object,), {'id': cid, 'type': query.message.chat.type})
            self.message = type('obj', (object,), {'chat_id': cid, 'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})

    fake_update = DummyUpdate(query.from_user.id, chat_id)
    if data == "quick_cmd_quiz": await quiz_command(fake_update, context)
    elif data == "quick_cmd_remaining": await remaininglimit_command(fake_update, context)
    elif data == "quick_cmd_hello": await hello_command(fake_update, context)
    elif data == "quick_cmd_help": await help_command(fake_update, context)
    elif data == "quick_cmd_feedback": await feedback_command(fake_update, context)
    elif data == "quick_cmd_toppers": await toppersname_handler(fake_update, context)
    elif data == "quick_cmd_rank": await myrank_handler(fake_update, context)
    elif data == "quick_cmd_profile": await myprofile_handler(fake_update, context)
    elif data == "quick_cmd_perf": await myperformance_handler(fake_update, context)
    elif data == "quick_cmd_state": await mywholestate_handler(fake_update, context)

# =====================================================================
#                          APPLICATION BUILDER
# =====================================================================

async def post_init(application: Application):
    commands = [
        BotCommand("quiz", "🚀 Start Computer Quiz"),
        BotCommand("remaininglimit", "⏳ Check Limit & Claim +10"),
        BotCommand("help", "📊 Help & Directory"),
        BotCommand("hello", "👋 Personalized Greeting"),
        BotCommand("feedback", "💬 Rating & Reviews"),
        BotCommand("myprofile", "👤 View Profile"),
        BotCommand("myrank", "🥇 Check Global Rank"),
        BotCommand("myperformance", "📈 Performance Rating"),
        BotCommand("mywholestate", "🎓 Complete Report"),
        BotCommand("toppersname", "🏆 Global Leaderboard"),
        BotCommand("stop", "⏸ Pause Active Quiz"),
        BotCommand("resume", "▶️ Resume Quiz")
    ]
    await application.bot.set_my_commands(commands)

def build_application() -> Application:
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Standard Command Handlers (HIGHEST PRIORITY)
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("hello", hello_command))
    app.add_handler(CommandHandler("remaininglimit", remaininglimit_command))
    app.add_handler(CommandHandler("feedback", feedback_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("toppersname", toppersname_handler))
    
    # Hidden Secret Admin Commands
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("showcontacts", showcontacts_command))
    app.add_handler(CommandHandler("showmarks", showmarks_command))
    app.add_handler(CommandHandler("showtoppers", showtoppers_command))
    app.add_handler(CommandHandler("showgender", showgender_command))
    app.add_handler(CommandHandler("showage", showage_command))
    app.add_handler(CommandHandler("cleardataofuser", cleardataofuser_command))
    app.add_handler(CommandHandler("increaselimitofuser", increaselimitofuser_command))
    app.add_handler(CommandHandler("addedsubscribers", addedsubscribers_command))

    app.add_handler(CommandHandler("myprofile", myprofile_handler))
    app.add_handler(CommandHandler("myrank", myrank_handler))
    app.add_handler(CommandHandler("myperformance", myperformance_handler))
    app.add_handler(CommandHandler("mywholestate", mywholestate_handler))
    
    # Onboarding Handler (Non-blocking fallback)
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
        per_chat=True, per_user=True
    )
    app.add_handler(onboarding_handler)

    # Keyboard Emoji Matchers
    app.add_handler(MessageHandler(filters.Regex(r"^/quiz"), quiz_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/remaininglimit"), remaininglimit_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/help"), help_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/hello"), hello_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/feedback"), feedback_command))
    app.add_handler(MessageHandler(filters.Regex(r"^/myprofile"), myprofile_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/myrank"), myrank_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/myperformance"), myperformance_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/mywholestate"), mywholestate_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/toppersname"), toppersname_handler))

    # Callback Handlers
    app.add_handler(CallbackQueryHandler(quiz_count_callback, pattern="^quiz_count_"))
    app.add_handler(CallbackQueryHandler(quiz_timer_callback, pattern="^quiz_timer_"))
    app.add_handler(CallbackQueryHandler(quick_command_callback, pattern="^quick_cmd_"))
    app.add_handler(CallbackQueryHandler(feedback_callback_handler, pattern="^fb_"))
    app.add_handler(CallbackQueryHandler(claim_bonus_callback, pattern="^claim_verify_sub$"))
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^adm_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_feedback_text))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    
    return app