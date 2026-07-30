import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters, ContextTypes
from app.database import save_user_profile, get_user_profile

NAME, TARGET_EXAM, PHONE_OTP, AGE_GENDER = range(4)

async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        raw_profile = get_user_profile(user.id)
        profile = dict(raw_profile) if raw_profile else {}
        
        if profile.get("is_verified"):
            full_name = profile.get("full_name") or user.full_name
            target_exam = profile.get("target_exam") or "General"
            phone = profile.get("phone_number") or "N/A"
            
            await update.message.reply_text(
                f"⚡ Welcome back, *{full_name}*!\n\n"
                f"🎯 **Target Exam:** `{target_exam}`\n"
                f"📱 **Phone:** `{phone}`\n\n"
                f"• Type /quiz to start practicing.\n"
                f"• Type /mywholestate to view your complete performance.",
                parse_mode="Markdown"
            )
            return ConversationHandler.END
    except Exception as e:
        logging.error(f"Error checking profile in start_onboarding: {e}")

    await update.message.reply_text(
        "👋 **Welcome to the Official Computer Quiz Portal!**\n\n"
        "To set up your student profile, let's complete a quick setup.\n\n"
        "👉 **Step 1/4:** Please reply with your **Full Name**:",
        parse_mode="Markdown"
    )
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
            f"Nice to meet you, *{name_text}*!\n\n"
            f"🎯 **Step 2/4:** Please select your **Target Exam** from the list below:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        return TARGET_EXAM
    except Exception as e:
        logging.error(f"Error in name_step: {e}")
        await update.message.reply_text("An error occurred. Please type your name again:")
        return NAME

async def target_exam_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        exam_text = update.message.text.strip()
        context.user_data["target_exam"] = exam_text
        
        contact_btn = KeyboardButton(text="📱 Share Verified Phone Number", request_contact=True)
        markup = ReplyKeyboardMarkup([[contact_btn]], one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            "📱 **Step 3/4:** Share your mobile number for account verification & ranking stats.\n\n"
            "Click the button below to share your number securely:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        return PHONE_OTP
    except Exception as e:
        logging.error(f"Error in target_exam_step: {e}")
        await update.message.reply_text("Please select your target exam from the keyboard option:")
        return TARGET_EXAM

async def phone_otp_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.contact:
            phone = update.message.contact.phone_number
        else:
            phone = update.message.text.strip()
            
        context.user_data["phone_number"] = phone
        
        await update.message.reply_text(
            f"✅ Mobile Number Received: `{phone}`\n\n"
            f"👉 **Step 4/4:** Please enter your **Age & Gender** (e.g., `22, Male` or `24, Female`):",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return AGE_GENDER
    except Exception as e:
        logging.error(f"Error in phone_otp_step: {e}")
        return PHONE_OTP

async def age_gender_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        parts = text.split(",")
        age = int(parts[0].strip()) if parts[0].strip().isdigit() else 21
        gender = parts[1].strip() if len(parts) > 1 else "Not Specified"
        
        user = update.effective_user
        save_user_profile(
            user_id=user.id,
            full_name=context.user_data.get("full_name", user.full_name),
            username=user.username or "N/A",
            phone=context.user_data.get("phone_number", "N/A"),
            target_exam=context.user_data.get("target_exam", "General"),
            age=age,
            gender=gender
        )
        
        await update.message.reply_text(
            "🎉 **Profile Creation Complete!**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Your student profile has been saved successfully.\n\n"
            "👉 Type /quiz anytime to choose your question target and start practicing!",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    except Exception as e:
        logging.error(f"Error in age_gender_step: {e}")
        await update.message.reply_text("Setup complete! Type /quiz to start practicing.")
        return ConversationHandler.END

async def cancel_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Setup cancelled. Type /start to try again when ready.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def get_onboarding_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("start", start_onboarding)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_step)],
            TARGET_EXAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, target_exam_step)],
            PHONE_OTP: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), phone_otp_step)],
            AGE_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_gender_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel_onboarding)],
        per_chat=True,
        per_user=True
    )