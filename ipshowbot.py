"""
ZYREX IP SNIFFER BOT - RAILWAY DEPLOYMENT READY
Complete bot with password protection, database, and Flask server
Optimized for Railway.app hosting
No API key required - simple and easy to deploy
"""

import os
import logging
import sqlite3
import json
import hashlib
import secrets
import asyncio
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ==================== CONFIGURATION (HARDCODED) ====================
# Replace these with your actual values
BOT_TOKEN = "8260905342:AAF6VR62-At2CUb5ZGBuORUG4-r-_DzZYqo"  # Get from @BotFather
OWNER_ID = 8909378644  # Your Telegram User ID (get from @userinfobot)
PASSWORD = "180310"  # Default password for bot access

# Flask port (Railway provides this via PORT environment variable)
PORT = int(os.getenv("PORT", default=5000))

# ==================== SETUP LOGGING ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ==================== DATABASE SETUP ====================
DB_PATH = "visitors.db"

def init_db():
    """Initialize SQLite database for storing visitor logs and passwords."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Visitors table
    c.execute("""
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            user_agent TEXT,
            referer TEXT,
            country TEXT,
            city TEXT,
            isp TEXT
        )
    """)
    
    # Stats table
    c.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        )
    """)
    
    # Password table
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Initialize total visitors counter
    c.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('total_visitors', 0)")
    
    # Set password
    default_password = hashlib.sha256(PASSWORD.encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('password', ?)", (default_password,))
    
    # Session tokens table
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            user_id INTEGER PRIMARY KEY,
            token TEXT,
            created_at TEXT,
            expires_at TEXT
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("Database initialized.")

def get_stored_password():
    """Get the stored password hash."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = 'password'")
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def update_password(new_password):
    """Update the password hash."""
    hashed = hashlib.sha256(new_password.encode()).hexdigest()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE config SET value = ? WHERE key = 'password'", (hashed,))
    conn.commit()
    conn.close()
    logger.info("Password updated successfully.")
    return True

def verify_password(password):
    """Verify if the provided password matches stored hash."""
    stored = get_stored_password()
    if not stored:
        return False
    hashed = hashlib.sha256(password.encode()).hexdigest()
    return hashed == stored

def create_session(user_id):
    """Create a session token for authenticated user."""
    token = secrets.token_hex(32)
    created_at = datetime.now().isoformat()
    expires_at = (datetime.now().replace(hour=23, minute=59, second=59)).isoformat()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO sessions (user_id, token, created_at, expires_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, token, created_at, expires_at))
    conn.commit()
    conn.close()
    return token

def check_session(user_id):
    """Check if user has a valid session."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT token, expires_at FROM sessions WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return False
    
    token, expires_at = result
    if datetime.now().isoformat() > expires_at:
        return False
    return True

def clear_session(user_id):
    """Clear a user's session."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def log_visitor(ip, user_agent=None, referer=None, location=None):
    """Log visitor IP and metadata to database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    timestamp = datetime.now().isoformat()
    country = location.get("country", "N/A") if location else "N/A"
    city = location.get("city", "N/A") if location else "N/A"
    isp = location.get("isp", "N/A") if location else "N/A"

    c.execute("""
        INSERT INTO visitors (ip, timestamp, user_agent, referer, country, city, isp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (ip, timestamp, user_agent, referer, country, city, isp))

    c.execute("UPDATE stats SET value = value + 1 WHERE key = 'total_visitors'")
    conn.commit()
    conn.close()
    logger.info(f"Logged visitor: {ip} from {country}")

def get_total_visitors():
    """Get total visitor count."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM stats WHERE key = 'total_visitors'")
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def get_recent_visitors(limit=10):
    """Get most recent visitors."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT ip, timestamp, country, city FROM visitors
        ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# ==================== FLASK SERVER ====================
flask_app = Flask(__name__)
CORS(flask_app)  # Allow cross-origin requests from Netlify

@flask_app.route("/", methods=["GET"])
def index():
    return "ZYREX IP Sniffer Bot is running on Railway!"

@flask_app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for Railway."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "total_visitors": get_total_visitors()
    })

@flask_app.route("/track", methods=["POST"])
def track_ip():
    """
    Endpoint for website to send visitor IPs.
    Expected JSON: {"ip": "1.2.3.4", "user_agent": "...", "referer": "..."}
    """
    try:
        data = request.get_json()
        if not data or "ip" not in data:
            return jsonify({"error": "Missing IP"}), 400

        ip = data["ip"]
        user_agent = data.get("user_agent")
        referer = data.get("referer")
        location = data.get("location")

        # Log to database
        log_visitor(ip, user_agent, referer, location)

        # Build notification message
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        country = location.get("country", "N/A") if location else "N/A"
        city = location.get("city", "N/A") if location else "N/A"

        message = f"""
🔴 <b>NEW VISITOR DETECTED</b>

🌐 <b>IP:</b> <code>{ip}</code>
📍 <b>Location:</b> {country} / {city}
🕐 <b>Time:</b> {timestamp}
📱 <b>User-Agent:</b> {user_agent[:80] if user_agent else 'N/A'}
🔗 <b>Referer:</b> {referer if referer else 'Direct'}

<b>Total Visitors:</b> {get_total_visitors()}
        """.strip()

        # Send notification to owner (asynchronously)
        asyncio.run_coroutine_threadsafe(
            send_telegram_message(OWNER_ID, message, parse_mode="HTML"),
            bot_loop
        )

        logger.info(f"IP {ip} tracked and notified.")
        return jsonify({"status": "success", "ip": ip}), 200

    except Exception as e:
        logger.error(f"Error tracking IP: {e}")
        return jsonify({"error": str(e)}), 500

# ==================== TELEGRAM BOT ====================
# Global reference to the bot loop
bot_loop = None
bot_app = None

async def send_telegram_message(chat_id, text, parse_mode="HTML"):
    """Send a message via Telegram bot."""
    try:
        await bot_app.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")

# ----- Bot Commands -----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - show bot info."""
    user_id = update.effective_user.id
    
    # Check if user is authenticated or is owner
    if user_id != OWNER_ID and not check_session(user_id):
        context.user_data['pending_command'] = 'start'
        await update.message.reply_text(
            "🔐 <b>Access Restricted</b>\n\n"
            "This bot is password protected.\n"
            "Please enter the password to continue.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_auth")]
            ])
        )
        return

    # Show main menu
    keyboard = [
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("📋 Recent Visitors", callback_data="recent")],
        [InlineKeyboardButton("🔗 Webhook Info", callback_data="webhook")],
        [InlineKeyboardButton("📈 Live Monitor", callback_data="monitor")],
    ]
    
    # Add admin options for owner
    if user_id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("🔑 Change Password", callback_data="change_password")])
        keyboard.append([InlineKeyboardButton("🔄 Reset All Sessions", callback_data="reset_sessions")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"""
🚀 <b>ZYREX IP SNIFFER BOT</b>

Welcome back, {update.effective_user.first_name}!

🟢 <b>System Status:</b> Active
📊 <b>Total Visitors:</b> {get_total_visitors()}
🕐 <b>Uptime:</b> Running
🔐 <b>Security:</b> Password Protected
🌐 <b>Hosted on:</b> Railway

Use the buttons below to manage your visitor logs.
        """.strip(),
        parse_mode="HTML",
        reply_markup=reply_markup,
    )

async def handle_password_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle password input from user."""
    user_id = update.effective_user.id
    password = update.message.text
    
    # Verify password
    if verify_password(password):
        # Create session
        create_session(user_id)
        await update.message.reply_text(
            "✅ <b>Authentication Successful!</b>\n\n"
            "You now have access to the bot for today.\n"
            "Use /start to see the main menu.",
            parse_mode="HTML"
        )
        # Execute pending command if any
        pending = context.user_data.get('pending_command')
        if pending:
            context.user_data['pending_command'] = None
            if pending == 'start':
                await start(update, context)
            else:
                command_map = {
                    'stats': stats,
                    'recent': recent,
                    'export_logs': export_logs,
                    'clear_logs': clear_logs
                }
                if pending in command_map:
                    await command_map[pending](update, context)
    else:
        await update.message.reply_text(
            "❌ <b>Invalid Password!</b>\n\n"
            "Please try again or contact the owner.",
            parse_mode="HTML"
        )

async def cancel_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel authentication attempt."""
    query = update.callback_query
    await query.answer()
    context.user_data['pending_command'] = None
    await query.edit_message_text(
        "❌ Authentication cancelled.\n\n"
        "Use /start to try again."
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    action = query.data
    if action == "cancel_auth":
        await cancel_auth(update, context)
        return
    
    if action == "change_password" and user_id != OWNER_ID:
        await query.edit_message_text("⛔ Only the owner can change the password.")
        return
    
    if action == "reset_sessions" and user_id != OWNER_ID:
        await query.edit_message_text("⛔ Only the owner can reset sessions.")
        return
    
    # Check authentication
    if user_id != OWNER_ID and not check_session(user_id):
        context.user_data['pending_command'] = 'button_callback'
        context.user_data['pending_callback'] = action
        await query.edit_message_text(
            "🔐 <b>Session Expired</b>\n\n"
            "Please enter the password to continue.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_auth")]
            ])
        )
        return

    # Process actions
    if action == "stats":
        total = get_total_visitors()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        today = datetime.now().date().isoformat()
        c.execute("SELECT COUNT(*) FROM visitors WHERE DATE(timestamp) = ?", (today,))
        today_count = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT ip) FROM visitors")
        unique_ips = c.fetchone()[0]
        conn.close()

        await query.edit_message_text(
            f"""
📊 <b>VISITOR STATISTICS</b>

📌 <b>Total Visitors:</b> {total}
📆 <b>Today:</b> {today_count}
👤 <b>Unique IPs:</b> {unique_ips}

<i>Last updated: {datetime.now().strftime('%H:%M:%S')}</i>
            """.strip(),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="stats")],
                [InlineKeyboardButton("◀ Back to Menu", callback_data="back_to_menu")]
            ])
        )

    elif action == "recent":
        visitors = get_recent_visitors(10)
        if not visitors:
            await query.edit_message_text("No visitors yet.")
            return

        lines = ["📋 <b>RECENT VISITORS</b>\n"]
        for ip, ts, country, city in visitors:
            ts_short = ts[:16].replace("T", " ")
            loc = f"{country}/{city}" if country != "N/A" else "Unknown"
            lines.append(f"🌐 <code>{ip}</code>  |  {loc}  |  {ts_short}")

        text = "\n".join(lines)
        await query.edit_message_text(
            text[:4000],
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="recent")],
                [InlineKeyboardButton("◀ Back to Menu", callback_data="back_to_menu")]
            ])
        )

    elif action == "webhook":
        await query.edit_message_text(
            f"""
🔗 <b>WEBHOOK CONFIGURATION</b>

📡 <b>Endpoint:</b> <code>POST /track</code>
📨 <b>Expected JSON:</b>
{{
  "ip": "1.2.3.4",
  "user_agent": "Mozilla/...",
  "referer": "https://...",
  "location": {{
    "country": "US",
    "city": "NYC",
    "isp": "Comcast"
  }}
}}

<b>Flask Server:</b> Railway dynamic URL

<i>Add this endpoint to your website's JavaScript.</i>
            """.strip(),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀ Back to Menu", callback_data="back_to_menu")]
            ])
        )

    elif action == "monitor":
        await query.edit_message_text(
            """
📈 <b>LIVE MONITOR</b>

🟢 Bot is running and listening for visitors.
🔄 Each new visitor will be forwarded to your Telegram.

<b>Commands:</b>
/stats  - View statistics
/recent - View recent visitors
/export - Export all logs (CSV)
/clear  - Clear all logs (confirmation)

<i>Monitor mode: ACTIVE</i>
            """.strip(),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀ Back to Menu", callback_data="back_to_menu")]
            ])
        )

    elif action == "change_password":
        context.user_data['changing_password'] = True
        await query.edit_message_text(
            "🔑 <b>Change Password</b>\n\n"
            "Please send me the <b>new password</b> as a message.\n"
            "The password must be at least 8 characters long.\n\n"
            "Type <code>/cancel</code> to cancel.",
            parse_mode="HTML"
        )
        return

    elif action == "reset_sessions":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM sessions")
        conn.commit()
        conn.close()
        await query.edit_message_text(
            "✅ All user sessions have been reset.\n\n"
            "All users will need to re-authenticate with the password."
        )

    elif action == "back_to_menu":
        context.user_data['pending_command'] = None
        keyboard = [
            [InlineKeyboardButton("📊 Stats", callback_data="stats")],
            [InlineKeyboardButton("📋 Recent Visitors", callback_data="recent")],
            [InlineKeyboardButton("🔗 Webhook Info", callback_data="webhook")],
            [InlineKeyboardButton("📈 Live Monitor", callback_data="monitor")],
        ]
        if user_id == OWNER_ID:
            keyboard.append([InlineKeyboardButton("🔑 Change Password", callback_data="change_password")])
            keyboard.append([InlineKeyboardButton("🔄 Reset All Sessions", callback_data="reset_sessions")])
        
        await query.edit_message_text(
            f"""
🚀 <b>ZYREX IP SNIFFER BOT</b>

🟢 System Active
📊 Total Visitors: {get_total_visitors()}

Choose an option:
            """.strip(),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics."""
    user_id = update.effective_user.id
    if user_id != OWNER_ID and not check_session(user_id):
        context.user_data['pending_command'] = 'stats'
        await update.message.reply_text(
            "🔐 <b>Access Restricted</b>\n\n"
            "Please enter the password to continue.",
            parse_mode="HTML"
        )
        return

    total = get_total_visitors()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().date().isoformat()
    c.execute("SELECT COUNT(*) FROM visitors WHERE DATE(timestamp) = ?", (today,))
    today_count = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT ip) FROM visitors")
    unique_ips = c.fetchone()[0]
    conn.close()

    await update.message.reply_text(
        f"""
📊 <b>VISITOR STATISTICS</b>

📌 Total Visitors: {total}
📆 Today: {today_count}
👤 Unique IPs: {unique_ips}
        """.strip(),
        parse_mode="HTML",
    )

async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent visitors."""
    user_id = update.effective_user.id
    if user_id != OWNER_ID and not check_session(user_id):
        context.user_data['pending_command'] = 'recent'
        await update.message.reply_text(
            "🔐 <b>Access Restricted</b>\n\n"
            "Please enter the password to continue.",
            parse_mode="HTML"
        )
        return

    visitors = get_recent_visitors(10)
    if not visitors:
        await update.message.reply_text("No visitors yet.")
        return

    lines = ["📋 <b>Recent Visitors</b>:"]
    for ip, ts, country, city in visitors:
        ts_short = ts[:16].replace("T", " ")
        loc = f"{country}/{city}" if country != "N/A" else "Unknown"
        lines.append(f"🌐 <code>{ip}</code>  |  {loc}  |  {ts_short}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def export_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export all logs as CSV."""
    user_id = update.effective_user.id
    if user_id != OWNER_ID and not check_session(user_id):
        context.user_data['pending_command'] = 'export_logs'
        await update.message.reply_text(
            "🔐 <b>Access Restricted</b>\n\n"
            "Please enter the password to continue.",
            parse_mode="HTML"
        )
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM visitors ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No logs to export.")
        return

    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "IP", "Timestamp", "User-Agent", "Referer", "Country", "City", "ISP"])
    writer.writerows(rows)

    await update.message.reply_document(
        document=io.BytesIO(output.getvalue().encode("utf-8")),
        filename=f"visitors_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        caption="📊 Visitor logs export."
    )

async def clear_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all logs (requires confirmation)."""
    user_id = update.effective_user.id
    if user_id != OWNER_ID and not check_session(user_id):
        context.user_data['pending_command'] = 'clear_logs'
        await update.message.reply_text(
            "🔐 <b>Access Restricted</b>\n\n"
            "Please enter the password to continue.",
            parse_mode="HTML"
        )
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, clear all", callback_data="confirm_clear"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_clear"),
        ]
    ]
    await update.message.reply_text(
        "⚠️ <b>WARNING:</b> This will permanently delete ALL visitor logs.\n\nAre you sure?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def confirm_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and clear logs."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != OWNER_ID and not check_session(user_id):
        await query.edit_message_text("⛔ Unauthorized.")
        return

    if query.data == "confirm_clear":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM visitors")
        c.execute("UPDATE stats SET value = 0 WHERE key = 'total_visitors'")
        conn.commit()
        conn.close()
        await query.edit_message_text("✅ All logs cleared successfully.")
    else:
        await query.edit_message_text("❌ Clear operation cancelled.")

async def handle_password_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle password change request."""
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("⛔ Only the owner can change the password.")
        return

    new_password = update.message.text
    
    # Validate password strength
    if len(new_password) < 8:
        await update.message.reply_text(
            "❌ Password must be at least 8 characters long.\n\n"
            "Please send a new password or type /cancel to cancel."
        )
        return
    
    # Update password
    update_password(new_password)
    context.user_data['changing_password'] = False
    await update.message.reply_text(
        "✅ <b>Password Changed Successfully!</b>\n\n"
        f"New password: <code>{new_password}</code>\n\n"
        "⚠️ Please save this password securely.",
        parse_mode="HTML"
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation."""
    if context.user_data.get('changing_password'):
        context.user_data['changing_password'] = False
        await update.message.reply_text("❌ Password change cancelled.")
    else:
        await update.message.reply_text("❌ Operation cancelled.")

# ==================== MAIN APPLICATION ====================

def main():
    global bot_app, bot_loop

    # Initialize database
    init_db()
    logger.info(f"Starting ZYREX Bot on Railway - Port: {PORT}")

    # Setup bot
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    # FIXED: Use asyncio.get_event_loop() instead of bot_app.loop
    bot_loop = asyncio.get_event_loop()

    # Add handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("stats", stats))
    bot_app.add_handler(CommandHandler("recent", recent))
    bot_app.add_handler(CommandHandler("export", export_logs))
    bot_app.add_handler(CommandHandler("clear", clear_logs))
    bot_app.add_handler(CommandHandler("cancel", cancel))
    
    # Password input handler
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password_input))
    
    # Password change handler
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password_change))
    
    # Callback handlers
    bot_app.add_handler(CallbackQueryHandler(button_callback))
    bot_app.add_handler(CallbackQueryHandler(confirm_clear, pattern="^(confirm_clear|cancel_clear)$"))
    bot_app.add_handler(CallbackQueryHandler(cancel_auth, pattern="^cancel_auth$"))

    # Start Flask in a separate thread
    def run_flask():
        flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask server started on port {PORT}")

    # Start bot
    logger.info("ZYREX IP Sniffer Bot started successfully on Railway!")
    bot_app.run_polling()

if __name__ == "__main__":
    main()