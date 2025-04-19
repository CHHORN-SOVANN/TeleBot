import asyncio
import logging
import os
import re
from uuid import uuid4
from typing import Dict
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    BotCommand,
    BotCommandScopeDefault
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
import yt_dlp

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global user state
user_state: Dict[int, Dict] = {}

# Platforms and qualities
PLATFORMS = ["YouTube", "TikTok", "Facebook"]
QUALITIES = ["360p", "720p", "1080p", "2k"]

# Validate video URL
def is_valid_url(platform: str, url: str) -> bool:
    patterns = {
        "YouTube": r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+",
        "TikTok": r"(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/.+",  # Added "vt.tiktok.com" for short links
        "Facebook": r"(https?://)?(www\.|m\.)?facebook\.com/.+"
    }
    return re.match(patterns[platform], url) is not None

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📺 Download Video", callback_data="menu:download")]]
    await update.message.reply_text(
        "👋 *Welcome to the Video Downloader Bot!*\n\nChoose an option:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Menu handler
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "menu:download":
        keyboard = [[InlineKeyboardButton(p, callback_data=f"platform:{p}")] for p in PLATFORMS]
        await query.edit_message_text("Select a platform:", reply_markup=InlineKeyboardMarkup(keyboard))

# Button handler (platform and quality)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("platform:"):
        platform = data.split(":")[1]
        user_state[user_id] = {"platform": platform, "video_sent": False}
        keyboard = [[InlineKeyboardButton(q, callback_data=f"quality:{q}")] for q in QUALITIES]
        await query.edit_message_text(
            f"📥 Platform selected: *{platform}*\nNow choose video quality:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("quality:"):
        quality = data.split(":")[1]
        if user_id in user_state:
            user_state[user_id]["quality"] = quality
            await query.edit_message_text(
                f"🎞 Quality selected: *{quality}*\nNow send the video URL:",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("⚠ Session expired. Please restart with /start.")

# Handle video URL message
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    message = update.message.text.strip()

    if user_id not in user_state:
        await update.message.reply_text("⚠ Please start with /start to choose a platform.")
        return

    if user_state[user_id].get("video_sent"):
        await update.message.reply_text("✅ You've already downloaded a video. Start again with /start.")
        return

    platform = user_state[user_id].get("platform")
    quality = user_state[user_id].get("quality", "720p")

    if not is_valid_url(platform, message):
        await update.message.reply_text(f"❌ Invalid URL for {platform}. Try again.")
        return

    await update.message.reply_text("⏳ Downloading video, please wait...")

    try:
        output_dir = "downloads"
        os.makedirs(output_dir, exist_ok=True)
        file_token = uuid4().hex[:10]
        format_height = quality.replace("p", "")

        ydl_opts = {
            'format': f'best[height<={format_height}]/best',
            'outtmpl': f"{output_dir}/{file_token}.%(ext)s",
            'noplaylist': True,
            'quiet': True,
            'socket_timeout': 120,
            'retries': 10,
            'fragment_retries': 10,
            'continuedl': True,
            'noprogress': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(message, download=True)
            file_path = ydl.prepare_filename(info)

        if not os.path.exists(file_path):
            await update.message.reply_text("❌ Download failed: file not found.")
            return

        if os.path.getsize(file_path) > 2 * 1024 * 1024 * 1024:
            await update.message.reply_text("⚠ File too large (limit: 2GB). Try lower quality.")
            os.remove(file_path)
            return

        with open(file_path, 'rb') as f:
            await update.message.reply_video(video=InputFile(f), caption=info.get("title", "Downloaded video"))

        # Remove the file after successfully sending it
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"File {file_path} removed from downloads directory.")

        user_state[user_id]["video_sent"] = True  # Mark as sent
        await update.message.reply_text("✅ Video sent successfully!")

    except Exception as e:
        logger.error(f"Download error: {e}")
        await update.message.reply_text(f"Please wait a moment, the video is being downloaded. If it takes too long, please try again later.\n\nError: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        user_state[user_id]["video_sent"] = False  # Reset video sent state
        return

# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f"Error: {context.error}")

# Set Telegram menu button and commands
# Set Telegram menu button and commands
async def set_menu_and_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
    ], scope=BotCommandScopeDefault())

    await app.bot.set_chat_menu_button(menu_button={"type": "commands"})

# Main function
def main():
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        raise ValueError("❌ BOT_TOKEN is not set.")

    app = ApplicationBuilder().token(TOKEN).post_init(set_menu_and_commands).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu:"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_error_handler(error_handler)

    print("✅ Bot is running...")
    app.run_polling()


if __name__ == '__main__':
    main()
