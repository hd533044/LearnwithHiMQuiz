from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from app.config import ADMIN_USER_ID
from app.database import get_all_users, get_user_profile, get_today_attempts
from app.stats import calculate_overall_performance, calculate_user_rank

async def admin_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_USER_ID != 0 and user_id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ Unauthorized. This command is reserved for Bot Administrators.")
        return

    users = get_all_users()
    if not users:
        await update.message.reply_text("📁 No registered users found in database.")
        return

    keyboard = []
    for u in users[:15]:  # Paginated list
        btn_text = f"👤 {u['full_name']} (@{u['username'] or 'N/A'})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_user_{u['user_id']}")])

    markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👑 **Admin Dashboard - Registered Users Portal**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Total Registered Students:** `{len(users)}`\n\n"
        f"Click on any student below to view full profile, phone number, quiz scores, & limits:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

async def admin_user_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    target_id = int(query.data.replace("admin_user_", ""))
    profile = get_user_profile(target_id)
    
    if not profile:
        await query.edit_message_text("User record not found.")
        return

    attempted_today = get_today_attempts(target_id)
    score_out_of_100, total_mocks = calculate_overall_performance(target_id)
    rank = calculate_user_rank(target_id)

    msg = (
        f"📄 **Detailed Student Profile (Admin View)**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Name:** {profile['full_name']}\n"
        f"🏷 **Username:** @{profile['username'] or 'N/A'}\n"
        f"🆔 **Telegram ID:** `{profile['user_id']}`\n"
        f"📱 **Phone Number:** `{profile['phone_number'] or 'Not Provided'}`\n"
        f"🎯 **Target Exam:** {profile['target_exam']}\n"
        f"🎂 **Age / Gender:** {profile['age']} / {profile['gender']}\n"
        f"📅 **Joined Date:** {profile['joined_date']}\n\n"
        f"📈 **Academic & Quiz Metrics:**\n"
        f"• **Overall Score:** `{score_out_of_100} / 100`\n"
        f"• **Overall Rank:** #{rank}\n"
        f"• **Mocks Attempted:** {total_mocks}\n"
        f"• **Daily Target:** {profile['daily_target']} Qs\n"
        f"• **Attempted Today:** {attempted_today} / 50\n"
        f"• **Timer Setting:** {profile['timer_sec']}s per Q"
    )
    
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Users List", callback_data="admin_back_users")]])
    await query.edit_message_text(msg, reply_markup=back_btn, parse_mode="Markdown")

async def admin_back_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    users = get_all_users()
    keyboard = []
    for u in users[:15]:
        btn_text = f"👤 {u['full_name']} (@{u['username'] or 'N/A'})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_user_{u['user_id']}")])

    markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("👑 **Admin Dashboard - Registered Users Portal**\nSelect a user:", reply_markup=markup, parse_mode="Markdown")