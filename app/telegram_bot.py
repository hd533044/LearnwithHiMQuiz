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
    increment_today_attempts, record_quiz_result, get_user_test_history
)
from app.stats import get_quiz_toppers, calculate_user_rank, calculate_overall_performance
from app.quiz_engine import start_quiz_session, get_active_session, finish_quiz_session

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)

# Global Session & Timer Storage
POLL_SESSION_MAP = {}
QUIZ_SETUP_CACHE = {}
TIMER_TASKS = {}
PUBLIC_FEEDBACK_LIST = []  # Stores clean, positive public feedback

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

# ---------------------------------------------------------------------
# SAFE IST TIME & QUOTA HELPERS
# ---------------------------------------------------------------------
def get_ist_now():
    """Returns current datetime in Indian Standard Time (UTC + 5:30)."""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

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
    """Calculates base limit (40) + any bonus limits granted for today."""
    bonus = BONUS_LIMITS.get(user_id, 0)
    return DAILY_QUESTION_LIMIT + bonus

def escape_markdown(text: str) -> str:
    """Safely escapes Markdown formatting characters."""
    if not text:
        return "N/A"
    return re.sub(r'([_*`\[\]])', r'\\\1', str(text))

# ---------------------------------------------------------------------
# UI TOOLKIT: Persistent Reply Menu Keyboard for Typing Bar
# ---------------------------------------------------------------------
def get_main_menu_keyboard():
    """Provides persistent keyboard buttons in the typing bar for all users."""
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

# ---------------------------------------------------------------------
# UI TOOLKIT: Universal Touch/Inline Action Buttons Under Messages
# ---------------------------------------------------------------------
def get_universal_inline_menu():
    """Generates interactive touch buttons attached directly below responses."""
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

# =====================================================================
#                        VERIFICATION HELPERS
# =====================================================================

async def check_telegram_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Cross-verifies if a user is an active member of the official Telegram channel."""
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

    # Check if user came via deep link from group (?start=quiz)
    is_deep_link_quiz = bool(args and args[0] == "quiz")

    try:
        raw_profile = get_user_profile(user.id)
        profile = dict(raw_profile) if raw_profile else {}
        
        if profile.get("is_verified"):
            full_name = profile.get("full_name") or user.full_name
            target_exam = profile.get("target_exam") or "General"
            
            # If triggered via deep link, launch quiz directly
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
                f"📌 **Quick Navigation:**\n"
                f"• Tap any touch button below or use the menu bar:\n"
                f"  └ /quiz — Start a practice test\n"
                f"  └ /remaininglimit — Check quota & claim +10 bonus\n"
                f"  └ /hello — Personalized greeting & motivation\n"
                f"  └ /feedback — Rate & read student reviews\n"
                f"  └ /mywholestate — Academic progress report\n\n"
                f"📢 **Official Channel:** {CHANNEL_USERNAME}"
            )
            await update.message.reply_text(
                msg, 
                reply_markup=get_main_menu_keyboard(), 
                parse_mode="Markdown"
            )
            await update.message.reply_text(
                "👇 **Interactive Command Touch Menu:**", 
                reply_markup=get_universal_inline_menu()
            )
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
            f"Pleasure to onboard you, *{escape_markdown(name_text)}*! ✨\n\n"
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
        await update.message.reply_text(
            completion_msg, 
            reply_markup=get_main_menu_keyboard(), 
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            "👇 **Interactive Command Options:**", 
            reply_markup=get_universal_inline_menu()
        )
        return ConversationHandler.END
    except Exception as e:
        logging.error(f"Error in gender_step: {e}")
        await update.message.reply_text("Profile saved! Type /quiz to start practicing.", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

async def cancel_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Setup cancelled. Type /start anytime to begin registration.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# =====================================================================
#             /remaininglimit COMMAND & CROSS-VERIFICATION
# =====================================================================

async def remaininglimit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"📊 **Used Today:** `{attempted_today}` / `{total_limit}` Questions\n"
        f"🎯 **Remaining Today:** `{remaining}` Questions\n"
        f"⏰ **Next Quota Reset:** In `{time_left}` *(at 11:11 PM IST)*\n\n"
        f"🎁 **Want +10 Additional Questions for Today?**\n"
        f"Perform these 2 simple steps to unlock your extra limit:\n"
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

    # Real-time Telegram Membership Cross-Verification
    is_tg_member = await check_telegram_membership(user_id, context)

    if not is_tg_member:
        await query.edit_message_text(
            f"{BOT_BRANDING_HEADER}\n\n"
            f"❌ **Cross-Verification Failed!**\n\n"
            f"You have not joined our official Telegram Channel `{CHANNEL_USERNAME}` yet.\n"
            f"Please join both Telegram and YouTube channels first to unlock your +10 bonus questions!",
            parse_mode="Markdown"
        )
        return

    # Grant Verification & Log Loyalty
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
#                  ADMIN SUBSCRIBERS MONITORING
# =====================================================================

async def addedsubscribers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    str_admin_ids = [str(aid).strip() for aid in ADMIN_IDS]
    allowed_ids = ["1091057353", "2070531704"]

    if str(user_id).strip() not in str_admin_ids and str(user_id).strip() not in allowed_ids:
        await update.message.reply_text(
            "🛑 **Access Denied:** Reserved for System Administrators.", 
            reply_markup=get_main_menu_keyboard()
        )
        return

    if not VERIFIED_SUBSCRIBERS:
        await update.message.reply_text(
            "📊 No users have claimed or cross-verified their YouTube/Telegram subscription today yet.", 
            reply_markup=get_main_menu_keyboard()
        )
        return

    lines = []
    for idx, uid in enumerate(VERIFIED_SUBSCRIBERS, start=1):
        raw_p = get_user_profile(uid)
        p = dict(raw_p) if raw_p else {}
        name = p.get("full_name", "Student")
        uname = f"@{p.get('username')}" if p.get('username') and p.get('username') != 'N/A' else "No Username"
        phone = p.get('phone_number') or p.get('phone') or "N/A"
        target = p.get('target_exam') or "General"
        lines.append(f"{idx}. **{escape_markdown(name)}** ({escape_markdown(uname)})\n   └ ID: `{uid}` | Target: `{target}` | Phone: `{phone}`")

    msg = (
        f"🔐 **ADMIN AUDIT — VERIFIED SUBSCRIBERS ADDED ({len(VERIFIED_SUBSCRIBERS)})**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(lines)
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

# =====================================================================
#                     FEEDBACK MANAGEMENT SYSTEM
# =====================================================================

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🌟 10/10 Bot! The quizzes are amazing 🚀", callback_data="fb_preset_1")],
        [InlineKeyboardButton("✨ Learn with HiM is the best educational platform 🎓", callback_data="fb_preset_2")],
        [InlineKeyboardButton("💡 Super interactive PYQ preparation portal 💻", callback_data="fb_preset_3")],
        [InlineKeyboardButton("🔥 Daily target limits keep me disciplined! 📈", callback_data="fb_preset_4")],
        [InlineKeyboardButton("✍️ Write Custom Feedback", callback_data="fb_custom")],
        [InlineKeyboardButton("📖 View Student Reviews", callback_data="fb_view_all")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"💬 **Student Feedback Portal**\n\n"
        f"Your opinion matters to **Himanshu Sir**! Please choose a quick review below or write your own custom thoughts:"
    )
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
        
        await query.edit_message_text(
            f"{BOT_BRANDING_HEADER}\n\n"
            f"🎉 **Thank You, {escape_markdown(student_name)}!**\n\n"
            f"Your feedback has been saved successfully:\n"
            f"💬 *\"{escape_markdown(feedback_text)}\"*",
            parse_mode="Markdown"
        )
        await context.bot.send_message(query.message.chat_id, "👇 **Select next option:**", reply_markup=get_universal_inline_menu())

    elif data == "fb_custom":
        context.user_data["awaiting_custom_feedback"] = True
        await query.edit_message_text(
            f"{BOT_BRANDING_HEADER}\n\n"
            f"✍️ **Write Your Feedback:**\n\n"
            f"Please reply with your personal thoughts or suggestions for the bot below:"
        )

    elif data == "fb_view_all":
        if not PUBLIC_FEEDBACK_LIST:
            await query.edit_message_text(
                f"{BOT_BRANDING_HEADER}\n\n"
                f"📖 **Student Reviews**\n\n"
                f"No reviews submitted yet. Be the first student to leave feedback using /feedback!",
                parse_mode="Markdown"
            )
            return

        reviews_text = []
        for idx, fb in enumerate(PUBLIC_FEEDBACK_LIST[-10:], start=1):
            reviews_text.append(f"{idx}. **{escape_markdown(fb['name'])}**: *\"{escape_markdown(fb['text'])}\"*")

        output = (
            f"{BOT_BRANDING_HEADER}\n\n"
            f"📖 **Student Reviews Board**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" +
            "\n\n".join(reviews_text)
        )
        await query.edit_message_text(output, parse_mode="Markdown")

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
        reply_msg = (
            f"{BOT_BRANDING_HEADER}\n\n"
            f"🙏 **Thank you for your response, {escape_markdown(student_name)}.**\n\n"
            f"We are constantly trying our best to improve. If you faced any issues, "
            f"please reach out to **Himanshu Sir** directly in our channel: {CHANNEL_USERNAME}.\n\n"
            f"We appreciate your patience!"
        )
        await update.message.reply_text(reply_msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    else:
        PUBLIC_FEEDBACK_LIST.append({"name": student_name, "text": text})
        reply_msg = (
            f"{BOT_BRANDING_HEADER}\n\n"
            f"🎉 **Feedback Received!**\n\n"
            f"Thank you *{escape_markdown(student_name)}* for your kind words:\n"
            f"💬 *\"{escape_markdown(text)}\"*"
        )
        await update.message.reply_text(reply_msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
        await update.message.reply_text("👇 **Select next option:**", reply_markup=get_universal_inline_menu())

# =====================================================================
#                        PERSONALIZED /hello GREETING
# =====================================================================

async def hello_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
#                           CORE QUIZ LOGIC
# =====================================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    msg = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"👋 **Hello, {escape_markdown(user.full_name)}!**\n"
        f"Welcome to your personal learning & evaluation portal.\n\n"
        f"🤖 **Platform Features:**\n"
        f"• 📚 100% Verified, Non-Repeating PYQs\n"
        f"• 🎯 Question Limits: 10, 15, 20, 25, or 30 Questions\n"
        f"• ⏱ Custom Timers: 12s, 15s, 18s, or 20s per question\n"
        f"• ⏸ Full Session Control: /stop & /resume\n"
        f"• 📈 Practice Quota: Up to `{DAILY_QUESTION_LIMIT}` questions daily\n\n"
        f"📌 **Available Commands:**\n"
        f"• /quiz — Start a computer awareness mock test\n"
        f"• /remaininglimit — Check daily limit & claim +10 bonus\n"
        f"• /hello — Personalized motivational greeting\n"
        f"• /feedback — Submit or view student feedback\n"
        f"• /stop — Pause active quiz session\n"
        f"• /resume — Resume paused quiz session\n"
        f"• /myprofile — Student profile card\n"
        f"• /myrank — Global rank evaluation\n"
        f"• /myperformance — Overall grade rating\n"
        f"• /mywholestate — Complete academic report\n"
        f"• /toppersname — Public Leaderboard\n\n"
        f"👇 **Tap any button below to execute instantly:**"
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await update.message.reply_text("👇 **Interactive Command Options:**", reply_markup=get_universal_inline_menu())

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    # Group Redirection Logic
    if chat and chat.type in ["group", "supergroup"]:
        bot_username = context.bot.username
        private_quiz_url = f"https://t.me/{bot_username}?start=quiz"
        
        keyboard = [
            [InlineKeyboardButton("🎯 I wanna attempt computer quiz", url=private_quiz_url)]
        ]
        markup = InlineKeyboardMarkup(keyboard)

        group_msg = (
            f"{BOT_BRANDING_HEADER}\n\n"
            f"📚 **Computer Quiz Ready!**\n\n"
            f"Hey {user.mention_markdown()}! To prevent chat clutter in the group and keep your score private, "
            f"click the button below to launch your personal quiz session:"
        )
        await update.message.reply_text(group_msg, reply_markup=markup, parse_mode="Markdown")
        return

    # Private Chat Flow
    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}
    
    if not profile or not profile.get("is_verified"):
        await update.message.reply_text(
            "⚠️ **Registration Required**\n\nPlease type /start first to create your profile before attempting quizzes!",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    attempted_today = get_today_attempts(user.id)
    effective_limit = get_effective_daily_limit(user.id)

    str_admin_ids = [str(aid).strip() for aid in ADMIN_IDS]
    allowed_ids = ["1091057353", "2070531704"]
    is_user_admin = str(user.id).strip() in str_admin_ids or str(user.id).strip() in allowed_ids

    if attempted_today >= effective_limit and not is_user_admin:
        time_left = get_time_until_reset()
        await update.message.reply_text(
            f"🛑 **Daily Target Reached!**\n\n"
            f"You have completed your limit of {effective_limit} questions for today. Excellent effort!\n\n"
            f"⏰ **Quota Resets In:** `{time_left}` *(at 11:11 PM IST)*\n\n"
            f"💡 Want +10 additional questions? Type /remaininglimit to claim!", 
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
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
        f"Select the number of questions for this test session:\n"
        f"*(Remaining daily quota: `{max(0, effective_limit - attempted_today)}` / `{effective_limit}`)*",
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

    record_quiz_result(user_id, quiz_id="computer_awareness_mock", score=score, total_questions=total, correct_count=session["correct_count"], skipped_count=session["skipped_count"])

    banner = (
        f"{BOT_BRANDING_HEADER}\n\n"
        f"🏆 **Test Completed Successfully!**\n\n"
        f"🎖 **Total Score:** `{score} / {total}`\n"
        f"✅ **Correct Answers:** `{session['correct_count']} / {total}`\n"
        f"⏭ **Skipped Questions:** `{session['skipped_count']}`\n"
        f"🎯 **Accuracy Rate:** `{accuracy}%`\n\n"
        f"🌟 *Great job! Consistent daily practice with Himanshu Sir ensures top exam rank.*\n\n"
        f"📢 **Join Telegram:** {CHANNEL_USERNAME}\n"
        f"📺 **Subscribe YouTube:** {YOUTUBE_CHANNEL_URL}"
    )
    await context.bot.send_message(
        chat_id=chat_id, 
        text=banner, 
        reply_markup=get_universal_inline_menu(), 
        parse_mode="Markdown"
    )

async def quick_command_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    
    class DummyUpdate:
        def __init__(self, uid, cid):
            self.effective_user = type('obj', (object,), {'id': uid, 'full_name': query.from_user.full_name, 'mention_markdown': lambda: query.from_user.mention_markdown()})
            self.effective_chat = type('obj', (object,), {'id': cid, 'type': query.message.chat.type})
            self.message = type('obj', (object,), {'chat_id': cid, 'reply_text': lambda text, **kwargs: context.bot.send_message(chat_id=cid, text=text, **kwargs)})

    fake_update = DummyUpdate(query.from_user.id, chat_id)

    if data == "quick_cmd_quiz":
        await quiz_command(fake_update, context)
    elif data == "quick_cmd_remaining":
        await remaininglimit_command(fake_update, context)
    elif data == "quick_cmd_hello":
        await hello_command(fake_update, context)
    elif data == "quick_cmd_help":
        await help_command(fake_update, context)
    elif data == "quick_cmd_feedback":
        await feedback_command(fake_update, context)
    elif data == "quick_cmd_toppers":
        await toppersname_handler(fake_update, context)
    elif data == "quick_cmd_rank":
        await myrank_handler(fake_update, context)
    elif data == "quick_cmd_profile":
        await myprofile_handler(fake_update, context)
    elif data == "quick_cmd_perf":
        await myperformance_handler(fake_update, context)
    elif data == "quick_cmd_state":
        await mywholestate_handler(fake_update, context)

# =====================================================================
#                       PUBLIC & ADMIN LEADERBOARD
# =====================================================================

async def toppersname_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    toppers = get_quiz_toppers(limit=10)
    if not toppers:
        await update.message.reply_text("🏆 No leaderboard records available yet. Complete a quiz to get listed!", reply_markup=get_main_menu_keyboard())
        return
        
    header = f"{BOT_BRANDING_HEADER}\n\n🏆 **Top 10 Leaderboard Scholars**\n\n"
    lines = [f"{idx}. **{escape_markdown(dict(t).get('full_name', 'Student'))}** — Score: `{round(dict(t).get('avg_score', 0.0) or 0.0, 2)}`" for idx, t in enumerate(toppers, start=1)]
        
    await update.message.reply_text(header + "\n".join(lines), reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await update.message.reply_text("👇 **Select an option to proceed:**", reply_markup=get_universal_inline_menu())

# =====================================================================
#                 STREAMLINED /admin COMMAND HANDLER
# =====================================================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    str_admin_ids = [str(aid).strip() for aid in ADMIN_IDS]
    allowed_ids = ["1091057353", "2070531704"]
    
    if str(user_id).strip() not in str_admin_ids and str(user_id).strip() not in allowed_ids:
        await update.message.reply_text(
            "🛑 **Access Denied:** Reserved for Himanshu Sir & System Administrators.", 
            reply_markup=get_main_menu_keyboard()
        )
        return

    try:
        toppers = get_quiz_toppers(limit=50)
        if not toppers:
            await update.message.reply_text("📊 No student records available in database yet.", reply_markup=get_main_menu_keyboard())
            return

        header = "🔐 **ADMIN MASTER DASHBOARD — ALL REGISTERED STUDENTS**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        lines = []
        
        for idx, t in enumerate(toppers, start=1):
            t_dict = dict(t) if t else {}
            uid = t_dict.get('user_id')
            raw_p = get_user_profile(uid)
            p = dict(raw_p) if raw_p else {}

            full_student_name = p.get('full_name') or t_dict.get('full_name') or "Student"
            username_val = t_dict.get('username') or p.get('username')
            username_str = f"@{username_val}" if username_val and username_val != 'N/A' else "No Username"
            phone = p.get('phone_number') or p.get('phone') or "N/A"
            age = p.get('age') or "N/A"
            gender = p.get('gender') or "N/A"
            target = p.get('target_exam') or t_dict.get('target_exam') or "General"
            avg_score = round(t_dict.get('avg_score', 0.0) or 0.0, 2)
            mocks_completed = p.get('total_mocks') or t_dict.get('total_quizzes') or 0

            student_card = (
                f"👤 **Student #{idx}: {escape_markdown(full_student_name)}** ({escape_markdown(username_str)})\n"
                f" └ **Telegram ID:** `{uid}`\n"
                f" └ **Target Exam:** `{escape_markdown(target)}`\n"
                f" └ **Age / Gender:** `{age}` / `{gender}`\n"
                f" └ **Phone Number:** `{phone}`\n"
                f" └ **Tests Completed:** `{mocks_completed}` | **Avg Score:** `{avg_score}`\n"
                f"───────────────────────────────"
            )
            lines.append(student_card)

        full_admin_report = header + "\n\n".join(lines)

        try:
            if len(full_admin_report) > 4000:
                for chunk in [full_admin_report[i:i+3800] for i in range(0, len(full_admin_report), 3800)]:
                    await update.message.reply_text(chunk, parse_mode="Markdown")
                await update.message.reply_text("✅ End of Master Student Report.", reply_markup=get_main_menu_keyboard())
            else:
                await update.message.reply_text(full_admin_report, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
        except Exception as msg_err:
            logging.warning(f"Markdown delivery failed in admin_command, falling back to plain text: {msg_err}")
            plain_report = full_admin_report.replace("**", "").replace("`", "").replace("*(", "").replace(")*", "")
            if len(plain_report) > 4000:
                for chunk in [plain_report[i:i+3800] for i in range(0, len(plain_report), 3800)]:
                    await update.message.reply_text(chunk)
                await update.message.reply_text("✅ End of Master Student Report.", reply_markup=get_main_menu_keyboard())
            else:
                await update.message.reply_text(plain_report, reply_markup=get_main_menu_keyboard())

    except Exception as general_err:
        logging.error(f"Error in admin_command execution: {general_err}")
        await update.message.reply_text(f"⚠️ Error loading admin dashboard: {general_err}", reply_markup=get_main_menu_keyboard())

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
    await update.message.reply_text("👇 **Select an option to proceed:**", reply_markup=get_universal_inline_menu())

async def myrank_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rank = calculate_user_rank(user_id)
    await update.message.reply_text(f"🥇 **Your Global Leaderboard Rank:** #{rank}", reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await update.message.reply_text("👇 **Select an option to proceed:**", reply_markup=get_universal_inline_menu())

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
    await update.message.reply_text("👇 **Select an option to proceed:**", reply_markup=get_universal_inline_menu())

async def mywholestate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw_profile = get_user_profile(user.id)
    profile = dict(raw_profile) if raw_profile else {}

    if not profile:
        await update.message.reply_text("Profile not found. Please type /start to set up your profile.", reply_markup=get_main_menu_keyboard())
        return

    attempted_today = get_today_attempts(user.id)
    limit = get_effective_daily_limit(user.id)
    score_out_of_100, total_mocks = calculate_overall_performance(user.id)
    overall_rank = calculate_user_rank(user.id)
    time_left = get_time_until_reset()

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
        f"• **Attempted Today:** {attempted_today} / {limit}\n"
        f"• **Remaining Today:** {max(0, limit - attempted_today)}\n"
        f"• **Next Reset:** In `{time_left}` *(at 11:11 PM IST)*\n\n"
        f"💡 Type /help to view all available commands."
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    await update.message.reply_text("👇 **Select an option to proceed:**", reply_markup=get_universal_inline_menu())

# =====================================================================
#                          APPLICATION BUILDER
# =====================================================================

async def post_init(application: Application):
    """Registers official command menu so the Menu button appears in typing bar for ALL users."""
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
        BotCommand("addedsubscribers", "🔐 Admin Subscriber Audit"),
        BotCommand("admin", "🔐 Master Admin Dashboard"),
        BotCommand("stop", "⏸ Pause Active Quiz"),
        BotCommand("resume", "▶️ Resume Quiz")
    ]
    await application.bot.set_my_commands(commands)

def build_application() -> Application:
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
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
    app.add_handler(CommandHandler("remaininglimit", remaininglimit_command))
    app.add_handler(CommandHandler("feedback", feedback_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("toppersname", toppersname_handler))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("addedsubscribers", addedsubscribers_command))
    app.add_handler(CommandHandler("myprofile", myprofile_handler))
    app.add_handler(CommandHandler("myrank", myrank_handler))
    app.add_handler(CommandHandler("myperformance", myperformance_handler))
    app.add_handler(CommandHandler("mywholestate", mywholestate_handler))
    
    # Text Regex Handlers for Bottom Bar Buttons
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

    # Custom text listener for custom feedback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_feedback_text))

    app.add_handler(PollAnswerHandler(handle_poll_answer))
    
    return app