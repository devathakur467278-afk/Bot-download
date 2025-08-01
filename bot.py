import os

os.chmod("ffmpeg", 0o755)
os.chmod("ffprobe", 0o755)

import math
import re
import yt_dlp
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from datetime import datetime

BOT_TOKEN = "8443998491:AAGlqRTFQdY16pb60-GyRl7Ekz0-M4BcCk4"
MAX_FILE_SIZE = 40 * 1024 * 1024  # 40MB in bytes
YOUR_PERSONAL_CHAT_ID = 8023509134

VALID_PLATFORMS = ["youtube.com", "youtu.be", "facebook.com", "instagram.com", "tiktok.com", "pinterest.com"]

# Enhanced user agent and headers to avoid bot detection
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.google.com/'
}

async def send_request_details_to_me(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Send request details to admin"""
    try:
        user = update.message.from_user
        platform = next((p for p in ["youtube", "facebook", "instagram", "tiktok", "pinterest"] if p in url.lower()), "unknown")
        
        await context.bot.send_message(
            chat_id=YOUR_PERSONAL_CHAT_ID,
            text=f"📥 New Link Request:\n\n"
                 f"👤 User: @{user.username or 'NoUsername'} (ID: {user.id})\n"
                 f"📛 Name: {user.full_name}\n"
                 f"🔗 Platform: {platform}\n"
                 f"🌐 Link: {url}\n"
        )
    except Exception as e:
        print(f"⚠️ Error sending details to admin: {e}")

def format_size(bytes_):
    if bytes_ is None:
        return "Unknown size"
    if bytes_ < 1024:
        return f"{bytes_} bytes"
    elif bytes_ < 1024*1024:
        return f"{round(bytes_/1024, 2)} KB"
    elif bytes_ < 1024*1024*1024:
        return f"{round(bytes_/1024/1024, 2)} MB"
    else:
        return f"{round(bytes_/1024/1024/1024, 2)} GB"

def safe_filename(name):
    return re.sub(r'[^\w\-_. ]', '_', name)

async def start(update: Update, context):
    await update.message.reply_text("📥 Send a YouTube/Facebook/Instagram/TikTok/Pinterest video link.")

async def handle_link(update: Update, context):
    url = update.message.text.strip()
    context.user_data.clear()

    if not any(p in url.lower() for p in VALID_PLATFORMS):
        await update.message.reply_text("❌ Invalid link. Please send a supported platform link: YouTube, Facebook, Instagram, TikTok, or Pinterest.")
        return

    try:
        await send_request_details_to_me(update, context, url)

        # Platform-specific configuration
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'noplaylist': True,
            'extract_flat': False,
            'headers': COMMON_HEADERS,
            'no_check_certificate': True,
            'ignoreerrors': True,
            'socket_timeout': 30,
            'extractor_args': {
                'youtube': {
                    'skip': ['hls', 'dash'],
                    'player_client': ['android_creator']
                },
                'instagram': {
                    'extract_flat': True
                },
                'facebook': {
                    'extract_flat': True
                },
                'tiktok': {
                    'extract_flat': True
                }
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        platform = ""
        for p in ["pinterest", "instagram", "tiktok", "facebook"]:
            if p in url.lower():
                platform = p
                break

        if platform:
            duration = info.get('duration', 1)
            tbr = info.get('tbr', 1000)
            estimated_size = (tbr * 1000 * duration) / 8
            
            if estimated_size > MAX_FILE_SIZE:
                await update.message.reply_text(
                    f"⚠️ This {platform.title()} video is too large ({format_size(estimated_size)}).\n\n"
                    "Telegram bots can only send files up to 40MB.\n"
                    "Please try a shorter video or use YouTube link for quality selection."
                )
                return
            
            await download_and_send(update, context, url, platform)
            return

        await show_quality_options(update, context, info, url)

    except yt_dlp.utils.DownloadError as e:
        if "Sign in to confirm" in str(e):
            await update.message.reply_text("⚠️ This video is restricted. Please try a different video.")
        else:
            await update.message.reply_text(f"❌ Download Error: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def show_quality_options(update, context, info, url):
    try:
        formats = info.get("formats", [])
        duration = info.get("duration", 0)
        choices = {}
        
        for fmt in formats:
            if fmt.get('vcodec') == 'none':
                continue
                
            res = fmt.get('format_note') or (f"{fmt.get('height')}p" if fmt.get('height') else "video")
            size = fmt.get('filesize') or fmt.get('filesize_approx')
            
            if not size and fmt.get('tbr') and duration:
                size = math.ceil(fmt["tbr"] * 1000 * duration / 8)
                
            prev = choices.get(res)
            if not prev or (size and size > (prev.get('filesize') or 0)):
                choices[res] = {"format_id": fmt["format_id"], "size": size}

        if not choices:
            await update.message.reply_text("❌ No downloadable formats found.")
            return

        context.user_data.update({"info": info, "choices": choices, "url": url})
        
        buttons = []
        for res, d in choices.items():
            size_text = format_size(d['size']) if d.get('size') else "Unknown size"
            if d.get('size') and d['size'] > MAX_FILE_SIZE:
                buttons.append([InlineKeyboardButton(
                    f"{res} - {size_text} (Too Large)", 
                    callback_data=f"too_large_{res}"
                )])
            else:
                buttons.append([InlineKeyboardButton(
                    f"{res} - {size_text}", 
                    callback_data=f"sel_{res}"
                )])
        
        if isinstance(update, Update):
            await update.message.reply_text(
                "Available qualities:", 
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await update.edit_message_text(
                "Available qualities:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

    except Exception as e:
        error_msg = f"❌ Error: {str(e)}"
        if isinstance(update, Update):
            await update.message.reply_text(error_msg)
        else:
            await update.edit_message_text(error_msg)

async def download_and_send(update, context, url, platform):
    fn = f"downloads/{platform}_video_{int(time.time())}.mp4"
    try:
        await update.message.reply_text(f"📥 Downloading {platform.title()} video...")
        os.makedirs("downloads", exist_ok=True)
        
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': fn,
            'merge_output_format': 'mp4',
            'quiet': True,
            'noplaylist': True,
            'headers': COMMON_HEADERS,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_creator']
                }
            },
            'socket_timeout': 30,
            'no_check_certificate': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        file_size = os.path.getsize(fn)
        if file_size > MAX_FILE_SIZE:
            await update.message.reply_text(
                f"⚠️ Sorry! This video is too large ({format_size(file_size)}).\n\n"
                "Telegram bots can only send files up to 40MB.\n"
                "Please try a shorter video."
            )
            os.remove(fn)
            return
            
        await update.message.reply_video(video=open(fn, 'rb'))
        os.remove(fn)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error downloading video: {str(e)}")
        if os.path.exists(fn):
            os.remove(fn)

async def handle_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("too_large_"):
        res = query.data.split("_", 2)[2]
        choice = context.user_data["choices"][res]
        
        buttons = []
        for quality, data in context.user_data["choices"].items():
            size_text = format_size(data['size']) if data.get('size') else "Unknown size"
            if data.get('size') and data['size'] > MAX_FILE_SIZE:
                buttons.append([InlineKeyboardButton(
                    f"{quality} - {size_text} (Too Large)", 
                    callback_data=f"too_large_{quality}"
                )])
            else:
                buttons.append([InlineKeyboardButton(
                    f"{quality} - {size_text}", 
                    callback_data=f"sel_{quality}"
                )])
        
        await query.edit_message_text(
            f"⚠️ {res} quality is too large ({format_size(choice['size'])}). Max 40MB allowed.\n"
            "Please select a lower quality:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return
    
    res = query.data.split("_", 1)[1]
    choice = context.user_data["choices"][res]
    context.user_data["selected"] = res

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Download", callback_data="do_yes")],
        [InlineKeyboardButton("❌ Cancel", callback_data="do_no")]
    ])
    
    await query.edit_message_text(
        f"Selected: {res} – {format_size(choice['size'])}\n"
        "This video is under Telegram's 40MB limit.\n"
        "Download?",
        reply_markup=kb
    )

async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "do_no":
        await query.edit_message_text("❌ Cancelled. Start again with /start.")
        return

    res = context.user_data["selected"]
    choice = context.user_data["choices"][res]
    url = context.user_data["url"]
    title = context.user_data["info"].get("title", "video")
    safe_title = safe_filename(title[:50])
    fn = f"downloads/{safe_title}_{res}.mp4"

    await query.edit_message_text(f"⏳ Downloading {res}... Please wait...")

    ydl_opts = {

        "ffmpeg_location": "./",
        'format': f"{choice['format_id']}+bestaudio/best",
        'outtmpl': fn,
        'merge_output_format': 'mp4',
        'quiet': True,
        'noplaylist': True,
        'headers': COMMON_HEADERS,
        'extractor_args': {
            'youtube': {
                'player_client': ['android_creator']
            }
        },
        'socket_timeout': 30,
        'no_check_certificate': True
    }

    os.makedirs("downloads", exist_ok=True)
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        file_size = os.path.getsize(fn)
        if file_size > MAX_FILE_SIZE:
            await query.message.reply_text(
                f"⚠️ Sorry! The downloaded video is {format_size(file_size)} which exceeds Telegram's 40MB limit.\n\n"
                "Please try a lower quality option /start again."
            )
            os.remove(fn)
            return
            
        await query.message.reply_video(video=open(fn, 'rb'))
        os.remove(fn)
        await query.message.reply_text("✅ Done! Send another link or /start again.")
        
    except Exception as e:
        await query.message.reply_text(f"❌ Error downloading: {str(e)}")
        if os.path.exists(fn):
            os.remove(fn)

def main():
    app = Application.builder().token(BOT_TOKEN).read_timeout(300).connect_timeout(60).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(handle_quality, pattern="^(sel|too_large)_"))
    app.add_handler(CallbackQueryHandler(handle_confirm, pattern="^do_"))
    print("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
