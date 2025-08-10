import os
import io
import json
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PollAnswerHandler
from Auth import authenticate
from SchedulerManager import add_schedule, scheduler, set_bot_instance, test_notification, get_failed_notifications, handle_poll_answer_tracking
from LeaderboardManager import leaderboard_manager
from flask import Flask, jsonify, request
import threading

BOT_TOKEN = '7997187971:AAEoCYjMX1lqXNPtZ3zEIeBpshezeLM0yaI'
USERS_JSON_FILE_ID = '103wefP2LJYCWCZsTPKM0ye1WFnI-Fk5o'

# Hardcoded group ID where all quizzes will be posted
HARDCODED_GROUP_ID = -1002526503801  # Replace with your actual group ID

def escape_markdown_v2(text):
    """Escape special characters for MarkdownV2"""
    if not text:
        return text
    # Convert to string if not already
    text = str(text)
    # Characters that need escaping in MarkdownV2
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

# Create bot instance
bot = Bot(token=BOT_TOKEN)

# Global application variable - will be initialized when needed
application = None

def get_application():
    """Get or create the Telegram application instance"""
    global application
    if application is None:
        application = Application.builder().token(BOT_TOKEN).build()
        # Setup handlers after creating application
        setup_handlers_webhook(application)
    return application

set_bot_instance(bot)

# Setup handlers at module level
def setup_handlers_webhook(app):
    app.add_handler(CommandHandler("start", start_browsing))
    app.add_handler(CallbackQueryHandler(handle_drive_callback, pattern="^(folder:|file:|back)"))
    app.add_handler(CallbackQueryHandler(handle_start_quiz_type, pattern="^start_(single|sequence)_quiz$"))
    app.add_handler(CallbackQueryHandler(handle_schedule_confirmation, pattern="^(confirm_schedule|cancel_schedule)$"))
    app.add_handler(CallbackQueryHandler(handle_sequence_callbacks, pattern="^(gap_|seq_)"))
    app.add_handler(CallbackQueryHandler(handle_final_sequence_confirmation, pattern="^(final_confirm_seq:|cancel_sequence)"))
    app.add_handler(CommandHandler("schedules", list_schedules))
    app.add_handler(CommandHandler("sequences", list_sequences))
    app.add_handler(CommandHandler("pause_sequence", pause_sequence_command))
    app.add_handler(CommandHandler("resume_sequence", resume_sequence_command))
    app.add_handler(CallbackQueryHandler(delete_schedule_callback, pattern=r"^delete_schedule:"))
    
    # Test commands
    app.add_handler(CommandHandler("test_notification", test_bot_notification))
    app.add_handler(CommandHandler("test_quiz", test_sample_quiz))
    app.add_handler(CommandHandler("failed_notifications", check_failed_notifications))
    app.add_handler(CommandHandler("set_users_file", set_users_file_command))
    app.add_handler(CommandHandler("test_leaderboard", test_leaderboard_command))
    app.add_handler(CommandHandler("get_chat_id", get_chat_id_command))
    app.add_handler(CommandHandler("test_group", test_group_access))
    app.add_handler(CommandHandler("test_scheduled", test_scheduled_execution))
    
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Text message handler
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))
    
    # Error handler
    app.add_error_handler(error_handler)

# Setup the handlers for webhook - this will be called after all functions are defined
# setup_handlers_webhook(application)

# Flask app for keeping alive on Render  
flask_app = Flask(__name__)

# Alias for Gunicorn compatibility
app = flask_app

@flask_app.route('/')
def home():
    """Main endpoint for UptimeRobot to ping"""
    return jsonify({
        "status": "alive",
        "message": "Quiz Bot is running!",
        "timestamp": datetime.now().isoformat(),
        "service": "telegram-quiz-bot"
    })

@flask_app.route('/setup_webhook', methods=['GET'])
def setup_webhook():
    """Endpoint to set up the webhook - call this once after deployment"""
    try:
        # Get the application instance
        app = get_application()
        
        # Set up webhook URL
        webhook_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://timer-quiz-y7gc.onrender.com')
        webhook_path = f"{webhook_url}/webhook"
        
        # Set webhook
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def set_webhook():
            await app.bot.set_webhook(webhook_path)
            return f"✅ Webhook set to: {webhook_path}"
            
        result = loop.run_until_complete(set_webhook())
        loop.close()
        
        return jsonify({
            "status": "success",
            "message": result,
            "webhook_url": webhook_path
        })
        
    except Exception as e:
        return jsonify({
            "status": "error", 
            "message": f"❌ Error setting webhook: {e}"
        }), 500

# Global flag to track if webhook is set up
_webhook_initialized = False

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    """Telegram webhook endpoint"""
    global _webhook_initialized
    
    try:
        # Initialize webhook on first request if not already done
        if not _webhook_initialized:
            print("🔧 Initializing webhook on first request...")
            _webhook_initialized = True
        
        # Get the JSON data from Telegram
        json_data = request.get_json()
        
        if json_data:
            # Get the application instance
            app = get_application()
            
            # Create an Update object from the JSON
            update = Update.de_json(json_data, app.bot)
            
            if update:
                # Process the update using the application's update queue
                import asyncio
                
                # Run the async function in the event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(app.process_update(update))
                loop.close()
                
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@flask_app.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        # Check if bot is responsive
        bot_info = bot.get_me()
        return jsonify({
            "status": "healthy",
            "bot_username": bot_info.username,
            "bot_id": bot_info.id,
            "scheduler_running": scheduler.running,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@flask_app.route('/stats')
def bot_stats():
    """Bot statistics endpoint"""
    try:
        from SchedulerManager import get_all_schedules_count
        schedule_count = get_all_schedules_count()
        
        return jsonify({
            "status": "active",
            "active_schedules": schedule_count,
            "scheduler_running": scheduler.running,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

def run_flask():
    """Run Flask app in a separate thread"""
    port = int(os.environ.get('PORT', 5000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

leaderboard_manager.users_file_id = USERS_JSON_FILE_ID

user_folder_stack = {}
user_file_selection = {}
user_states = {}
user_group_ids = {}  # Store group IDs for each user
GROUP_IDS_FILE = "user_group_ids.json"

# Load group IDs on startup
def load_group_ids():
    """Load user group IDs from file"""
    global user_group_ids
    try:
        if os.path.exists(GROUP_IDS_FILE):
            with open(GROUP_IDS_FILE, 'r') as f:
                user_group_ids = json.load(f)
                # Convert string keys back to integers
                user_group_ids = {int(k): v for k, v in user_group_ids.items()}
    except Exception as e:
        print(f"⚠️ Error loading group IDs: {e}")
        user_group_ids = {}

def save_group_ids():
    """Save user group IDs to file"""
    try:
        # Convert integer keys to strings for JSON
        data = {str(k): v for k, v in user_group_ids.items()}
        with open(GROUP_IDS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving group IDs: {e}")

# Load group IDs on module import
load_group_ids()

STATE_WAITING_FOR_DATE = "waiting_for_date"
STATE_WAITING_FOR_TIME = "waiting_for_time"
STATE_WAITING_FOR_TIMER = "waiting_for_timer"
STATE_WAITING_FOR_GROUP_ID = "waiting_for_group_id"
STATE_SEQUENCE_WAITING_FOR_DATE = "seq_waiting_for_date"
STATE_SEQUENCE_WAITING_FOR_TIME = "seq_waiting_for_time"
STATE_SEQUENCE_WAITING_FOR_QUIZ_TIMER = "seq_waiting_for_quiz_timer"

# User sequence data tracking
user_sequence_data = {}

# Remove duplicate setup_handlers - using setup_handlers_webhook instead

def shorten_name(name, max_len=25):
    return name if len(name) <= max_len else name[:22] + "..."

async def start_browsing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow in private chat
    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot. Please message me directly.")
        return
    
    chat_id = update.effective_chat.id
    
    # Clear any existing user data
    if chat_id in user_states:
        del user_states[chat_id]
    if chat_id in user_file_selection:
        del user_file_selection[chat_id]
    if chat_id in user_sequence_data:
        del user_sequence_data[chat_id]
    
    # Show quiz type selection first
    keyboard = [
        [InlineKeyboardButton("📝 Single Quiz", callback_data="start_single_quiz")],
        [InlineKeyboardButton("📚 Sequential Quizzes", callback_data="start_sequence_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎯 *Welcome to Quiz Scheduler\\!*\n\n"
        "Choose what you'd like to create:",
        reply_markup=reply_markup,
        parse_mode="MarkdownV2"
    )

async def handle_start_quiz_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quiz type selection from /start command"""
    query = update.callback_query
    await query.answer()
    
    # Get chat_id safely
    try:
        chat_id = update.effective_chat.id
    except:
        chat_id = query.message.chat.id
    
    quiz_type = query.data.split("_")[1]  # single or sequence
    
    if quiz_type == "single":
        # Initialize for single quiz - start browsing files
        root_folder_id = '1xZNjra8vnE0v2JFpZtqUeB1qVpQlOuiQ'
        user_folder_stack[chat_id] = [root_folder_id]
        await query.edit_message_text("📂 *Single Quiz Mode*\n\nBrowsing files\\.\\.\\.", parse_mode="MarkdownV2")
        await list_drive_contents_for_callback(query, context, root_folder_id)
    elif quiz_type == "sequence":
        # Initialize for sequence - start with date/time first
        user_sequence_data[chat_id] = {
            "quizzes": [],
            "current_step": "date"
        }
        user_states[chat_id] = STATE_SEQUENCE_WAITING_FOR_DATE
        
        await query.edit_message_text(
            "📚 *Sequential Quiz Mode*\n\n"
            "📅 Send the start date for your sequence (e.g., 12-08-2025):"
        )

async def list_drive_contents_for_callback(query, context: ContextTypes.DEFAULT_TYPE, folder_id: str):
    """List drive contents for callback query (used when editing message)"""
    # Get chat_id safely
    try:
        chat_id = query.message.chat.id
    except:
        chat_id = query.from_user.id
    
    try:
        service = authenticate()
        keyboard = []

        query_str = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query_str, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])

        for item in items:
            name = shorten_name(item['name'])
            if item['mimeType'] == 'application/vnd.google-apps.folder':
                keyboard.append([InlineKeyboardButton(f"📁 {name}", callback_data=f"folder:{item['id']}")])
                context.user_data[f"folder_{item['id']}"] = item
            else:
                keyboard.append([InlineKeyboardButton(f"📄 {name}", callback_data=f"file:{item['id']}")])
                context.user_data[f"file_{item['id']}"] = {
                    'id': item['id'],
                    'name': item['name'],
                    'folder_id': folder_id
                }

        if len(user_folder_stack.get(chat_id, [])) > 1:
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])

        if not keyboard:
            await query.edit_message_text("📁 This folder is empty.")
            return

        message = "Select a folder or file:"
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        await query.edit_message_text(f"❌ Error accessing Google Drive: {e}")

async def list_drive_contents(update_or_cb, context: ContextTypes.DEFAULT_TYPE, folder_id: str):
    chat_id = update_or_cb.effective_chat.id
    
    try:
        service = authenticate()
        keyboard = []

        query = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])

        if not items:
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = "📂 This folder is empty."
        else:
            for item in items:
                name = shorten_name(item['name'])
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    keyboard.append([InlineKeyboardButton(f"📁 {name}", callback_data=f"folder:{item['id']}")])
                elif item['name'].endswith(".json"):
                    file_key = f"file_{item['id']}"
                    context.user_data[file_key] = {
                        'id': item['id'],
                        'name': item['name'],
                        'folder_id': folder_id
                    }
                    keyboard.append([InlineKeyboardButton(f"📄 {name}", callback_data=f"file:{item['id']}")])

            if len(user_folder_stack.get(chat_id, [])) > 1:
                keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
            
            message = "Select a folder or file:"

        reply_markup = InlineKeyboardMarkup(keyboard)

        if update_or_cb.callback_query:
            await update_or_cb.callback_query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update_or_cb.message.reply_text(message, reply_markup=reply_markup)
            
    except Exception as e:
        error_message = f"❌ Error accessing Google Drive: {str(e)}"
        if update_or_cb.callback_query:
            await update_or_cb.callback_query.edit_message_text(error_message)
        else:
            await update_or_cb.message.reply_text(error_message)


async def handle_drive_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    if query.data.startswith("folder:"):
        folder_id = query.data.split(":", 1)[1]
        user_folder_stack[chat_id].append(folder_id)
        await list_drive_contents(update, context, folder_id)

    elif query.data == "back":
        if len(user_folder_stack.get(chat_id, [])) > 1:
            user_folder_stack[chat_id].pop()
            parent_folder = user_folder_stack[chat_id][-1]
            await list_drive_contents(update, context, parent_folder)

    elif query.data.startswith("file:"):
        file_id = query.data.split(":", 1)[1]
        file_key = f"file_{file_id}"
        
        file_info = context.user_data.get(file_key)
        if not file_info:
            await query.edit_message_text("❌ File information not found. Please try again.")
            return
        
        # Check if user is in sequence mode
        if chat_id in user_sequence_data:
            seq_data = user_sequence_data[chat_id]
            
            if seq_data.get("current_step") == "select_first_quiz":
                # First quiz in sequence
                seq_data["temp_quiz"] = {
                    "file_id": file_info['id'],
                    "file_name": file_info['name'],
                    "folder_id": file_info['folder_id']
                }
                seq_data["current_step"] = "first_quiz_timer"
                user_states[chat_id] = STATE_SEQUENCE_WAITING_FOR_QUIZ_TIMER
                
                await query.edit_message_text(
                    f"📚 *Quiz Sequence Setup*\n\n"
                    f"✅ *1st Quiz:* {file_info['name'].replace('-', '\\-').replace('.', '\\.')}\n\n"
                    f"⏱️ Enter timer seconds per question for this quiz \\(5\\-300\\):",
                    parse_mode="MarkdownV2"
                )
                return
                
            elif seq_data.get("current_step") == "select_next_quiz":
                # Additional quiz in sequence
                quiz_number = len(seq_data["quizzes"]) + 1
                seq_data["temp_quiz"] = {
                    "file_id": file_info['id'],
                    "file_name": file_info['name'],
                    "folder_id": file_info['folder_id']
                }
                seq_data["current_step"] = "next_quiz_timer"
                seq_data["current_quiz_number"] = quiz_number
                user_states[chat_id] = STATE_SEQUENCE_WAITING_FOR_QUIZ_TIMER
                
                await query.edit_message_text(
                    f"📚 *Quiz Sequence Setup*\n\n"
                    f"✅ *Quiz {quiz_number}:* {file_info['name'].replace('-', '\\-').replace('.', '\\.')}\n\n"
                    f"⏱️ Enter timer seconds per question for this quiz \\(5\\-300\\):",
                    parse_mode="MarkdownV2"
                )
                return
        
        # Single quiz mode (normal flow)
        user_file_selection[chat_id] = {
            "file_id": file_info['id'],
            "file_name": file_info['name'],
            "folder_id": file_info['folder_id']
        }
        
        user_states[chat_id] = STATE_WAITING_FOR_DATE
        await query.edit_message_text(
            f"✅ You selected file: *{file_info['name'].replace('-', '\\-').replace('.', '\\.')}*\n\n"
            f"📅 Send the date to schedule \\(e\\.g\\., 12\\-08\\-2025\\):",
            parse_mode="MarkdownV2"
        )
        return


async def handle_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if user_states.get(chat_id) != STATE_WAITING_FOR_DATE:
        return
        
    if chat_id not in user_file_selection:
        await update.message.reply_text("❌ No file selected. Please use /start to select a file first.")
        return
        
    date_text = update.message.text.strip()
    
    try:
        from datetime import datetime
        datetime.strptime(date_text, "%d-%m-%Y")
    except ValueError:
        await update.message.reply_text("❌ Invalid date format. Please use DD-MM-YYYY format (e.g., 12-08-2025):")
        return
    
    user_file_selection[chat_id]["date"] = date_text
    user_states[chat_id] = STATE_WAITING_FOR_TIME  # Change state to waiting for time
    await update.message.reply_text("⏰ Send the time in 24hr format (e.g., 17:00):")


async def handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if user_states.get(chat_id) != STATE_WAITING_FOR_TIME:
        return
    
    if chat_id not in user_file_selection:
        await update.message.reply_text("❌ No file selected. Please use /start to select a file first.")
        return
    
    if "date" not in user_file_selection[chat_id]:
        await update.message.reply_text("❌ Please send the date first.")
        return
        
    time_text = update.message.text.strip()
    
    try:
        from datetime import datetime
        datetime.strptime(time_text, "%H:%M")
    except ValueError:
        await update.message.reply_text("❌ Invalid time format. Please use HH:MM format (e.g., 17:00):")
        return
    
    user_file_selection[chat_id]["time"] = time_text
    user_states[chat_id] = STATE_WAITING_FOR_TIMER  
    await update.message.reply_text("⏱️ Set timer per question in seconds (5-300 seconds, e.g., 15):")


async def handle_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if user_states.get(chat_id) != STATE_WAITING_FOR_TIMER:
        return
    
    if chat_id not in user_file_selection:
        await update.message.reply_text("❌ No file selected. Please use /start to select a file first.")
        return
    
    if "time" not in user_file_selection[chat_id]:
        await update.message.reply_text("❌ Please send the date and time first.")
        return
        
    timer_text = update.message.text.strip()

    try:
        timer_seconds = int(timer_text)
        if timer_seconds < 5 or timer_seconds > 300:
            await update.message.reply_text("❌ Timer must be between 5 and 300 seconds. Please try again:")
            return
    except ValueError:
        await update.message.reply_text("❌ Invalid timer format. Please enter a number between 5 and 300:")
        return
    
    user_file_selection[chat_id]["timer_seconds"] = timer_seconds
    user_states[chat_id] = None  # Clear state
    
    data = user_file_selection[chat_id]
    confirm_msg = (
    f"✅ You selected file: *{data['file_name'].replace('-', '\\-').replace('.', '\\.')}*\n"
    f"🗓 Date: `{data['date'].replace('-', '\\-')}`\n"
    f"⏰ Time: `{data['time'].replace(':', '\\:')}`\n"
    f"⏱️ Timer: `{str(data['timer_seconds'])} seconds per question`\n\n"
    f"Do you want to confirm this schedule?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data="confirm_schedule"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_schedule")
        ]
    ]
    await update.message.reply_text(confirm_msg, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_sequence_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle date input for sequence scheduling"""
    chat_id = update.effective_chat.id
    date_text = update.message.text.strip()
    
    try:
        date_obj = datetime.strptime(date_text, "%d-%m-%Y")
        user_sequence_data[chat_id]["date"] = date_text
        user_sequence_data[chat_id]["date_obj"] = date_obj
        user_states[chat_id] = STATE_SEQUENCE_WAITING_FOR_TIME
        await update.message.reply_text("⏰ Send the start time (e.g., 14:30):")
    except ValueError:
        await update.message.reply_text("❌ Invalid date format. Please use DD-MM-YYYY (e.g., 12-08-2025):")

async def handle_sequence_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle time input for sequence scheduling"""
    chat_id = update.effective_chat.id
    time_text = update.message.text.strip()
    
    try:
        time_obj = datetime.strptime(time_text, "%H:%M").time()
        seq_data = user_sequence_data[chat_id]
        
        # Combine date and time
        combined_datetime = datetime.combine(seq_data["date_obj"], time_obj)
        seq_data["time"] = time_text
        seq_data["scheduled_datetime"] = combined_datetime
        
        user_states[chat_id] = None  # Clear state
        
        await update.message.reply_text(
            f"✅ Sequence scheduled for {seq_data['date']} at {time_text}\n\n"
            f"📂 Now use /start to browse and select your first quiz file."
        )
        
    except ValueError:
        await update.message.reply_text("❌ Invalid time format. Please use HH:MM (e.g., 14:30):")

async def handle_sequence_quiz_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle timer input for sequence quiz"""
    chat_id = update.effective_chat.id
    timer_text = update.message.text.strip()
    
    try:
        timer_seconds = int(timer_text)
        if timer_seconds < 5 or timer_seconds > 300:
            await update.message.reply_text("❌ Timer must be between 5 and 300 seconds. Please try again:")
            return
    except ValueError:
        await update.message.reply_text("❌ Invalid timer format. Please enter a number between 5 and 300:")
        return
    
    seq_data = user_sequence_data[chat_id]
    seq_data["temp_quiz"]["timer_seconds"] = timer_seconds
    
    # Check if this is the first quiz
    if seq_data.get("current_step") == "first_quiz_timer":
        # First quiz - ask for gap time after first quiz
        seq_data["current_step"] = "first_gap"
        user_states[chat_id] = None
        
        from SequenceManager import get_gap_time_keyboard
        keyboard = get_gap_time_keyboard()
        
        await update.message.reply_text(
            f"✅ *Quiz 1 Timer:* {timer_seconds}s per question\n\n"
            f"⏳ Select gap time before *Quiz 2*:",
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
        )
        return
    
    # This is for 2nd, 3rd, etc. quiz - add to sequence and show options
    elif seq_data.get("current_step") == "next_quiz_timer":
        quiz_number = seq_data.get("current_quiz_number", len(seq_data["quizzes"]) + 1)
        
        # Add the quiz to sequence (gap will be set when user selects it)
        seq_data["temp_quiz"]["gap_minutes"] = 0  # Will be updated when gap is selected
        seq_data["quizzes"].append(seq_data["temp_quiz"])
        
        user_states[chat_id] = None
        
        from SequenceManager import get_sequence_action_keyboard
        keyboard = get_sequence_action_keyboard()
        
        quiz_count = len(seq_data["quizzes"])
        await update.message.reply_text(
            f"✅ *Quiz {quiz_count} Timer:* {timer_seconds}s per question\n\n"
            f"📊 *Current sequence:* {quiz_count} quiz{'s' if quiz_count > 1 else ''}\n\n"
            f"What would you like to do next?",
            reply_markup=keyboard
        )


async def handle_group_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle group ID input when user is in GROUP_ID state"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    try:
        group_id = int(text)
        user_group_ids[user_id] = group_id
        user_states[user_id] = None  # Clear state
        save_group_ids()  # Save to file
        
        # Test if bot can send to the group
        try:
            await bot.send_message(
                chat_id=group_id,
                text="✅ Quiz bot connected! Quizzes will be posted here.\n\nℹ️ All quiz management (scheduling, browsing files) happens in private chat with the bot."
            )
            await update.message.reply_text(f"✅ Group ID set successfully: {group_id}\n\n📋 Your scheduled quizzes will now be posted in this group!")
        except Exception as e:
            await update.message.reply_text(f"❌ Cannot send messages to group {group_id}. Make sure:\n• I'm added to the group\n• I have admin permissions\n• Group ID is correct")
            user_group_ids.pop(user_id, None)  # Remove invalid group ID
            save_group_ids()  # Save updated state
            
    except ValueError:
        await update.message.reply_text("❌ Invalid group ID. Please provide a valid number:")


async def handle_schedule_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    await query.answer()

    if query.data == "cancel_schedule":
        user_file_selection.pop(chat_id, None)
        user_states.pop(chat_id, None)  # Clear state
        await query.edit_message_text("❌ Schedule cancelled.")
        return

    data = user_file_selection.get(chat_id)
    if not data:
        await query.edit_message_text("⚠️ Schedule data missing.")
        return

    try:
        file_path = os.path.join(os.getcwd(), data['file_name'])
        service = authenticate()
        request = service.files().get_media(fileId=data['file_id'])
        
        # Import here to avoid module loading issues
        from googleapiclient.http import MediaIoBaseDownload
        
        with open(file_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()

        add_schedule(
            file_id=data['file_id'],
            file_name=data['file_name'],
            path=file_path,
            date_str=data['date'],
            time_str=data['time'],
            user_id=chat_id,
            timer_seconds=data.get('timer_seconds', 10)  # Default to 10 seconds if not set
        )

        await query.edit_message_text(f"✅ Schedule confirmed. File downloaded to `{file_path}`")
        user_file_selection.pop(chat_id, None)
        user_states.pop(chat_id, None)  # Clear state
    except Exception as e:
        await query.edit_message_text(f"❌ Error creating schedule: {str(e)}")

def get_file_metadata(service, file_id):
    try:
        file = service.files().get(fileId=file_id, fields="id, name").execute()
        return file
    except Exception as e:
        print(f"Error retrieving file metadata: {e}")
        return {}

async def list_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow in private chat
    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
        
    from SchedulerManager import get_schedules_by_user
    import pytz
    from datetime import datetime
    
    try:
        user_id = update.effective_user.id
        schedules = get_schedules_by_user(user_id)
        
        if not schedules:
            await update.message.reply_text("📭 No schedules found.")
            return

        message_text = "📅 <b>Your Scheduled Files:</b>\n\n"
        keyboard_buttons = []
        
        for i, schedule in enumerate(schedules, 1):
            schedule_id = schedule["id"]
            file_name = schedule["file_name"]
            
            try:
                scheduled_utc = datetime.fromisoformat(schedule["scheduled_at"].replace('Z', '+00:00'))
                ist_tz = pytz.timezone('Asia/Kolkata')
                scheduled_ist = scheduled_utc.astimezone(ist_tz)
                run_time = scheduled_ist.strftime('%d %B %Y, %I:%M %p IST')
            except:
                run_time = "Unknown time"

            message_text += f"{i}. 📁 <b>{file_name}</b>\n   🕒 <i>{run_time}</i>\n\n"
            
            keyboard_buttons.append([
                InlineKeyboardButton(f"🗑️ Delete #{i}", callback_data=f"delete_schedule:{schedule_id}")
            ])
        
        if len(message_text) > 4000:
            message_text = message_text[:4000] + "...\n\n<i>Some schedules truncated due to length limit.</i>"
        
        keyboard = InlineKeyboardMarkup(keyboard_buttons)
        await update.message.reply_text(message_text, parse_mode='HTML', reply_markup=keyboard)
        
    except Exception as e:
        print(f"Error in list_schedules: {e}")
        try:
            await update.message.reply_text(
                "❌ Sorry, there was an error retrieving your schedules. Please try again later."
            )
        except:
            print("Failed to send error message - network issue")

async def delete_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from SchedulerManager import delete_schedule
    
    query = update.callback_query
    await query.answer()

    schedule_id = query.data.split(":")[1]
    
    try:
        delete_schedule(schedule_id)
        await query.edit_message_text("✅ Schedule deleted successfully.")
    except Exception as e:
        await query.edit_message_text(f"⚠️ Error deleting schedule: {str(e)}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages and route to appropriate handler based on user state"""
    # Only process text messages in private chat
    if update.message.chat.type != "private":
        return
        
    chat_id = update.effective_chat.id
    user_state = user_states.get(chat_id)
    
    if user_state == STATE_WAITING_FOR_DATE:
        await handle_date(update, context)
    elif user_state == STATE_WAITING_FOR_TIME:
        await handle_time(update, context)
    elif user_state == STATE_WAITING_FOR_TIMER:
        await handle_timer(update, context)
    elif user_state == STATE_SEQUENCE_WAITING_FOR_DATE:
        await handle_sequence_date(update, context)
    elif user_state == STATE_SEQUENCE_WAITING_FOR_TIME:
        await handle_sequence_time(update, context)
    elif user_state == STATE_SEQUENCE_WAITING_FOR_QUIZ_TIMER:
        await handle_sequence_quiz_timer(update, context)
    # Removed GROUP_ID handling since using hardcoded group

async def handle_sequence_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle date input for sequence"""
    chat_id = update.effective_chat.id
    date_text = update.message.text.strip()
    
    try:
        from datetime import datetime
        parsed_date = datetime.strptime(date_text, "%d-%m-%Y")
        
        seq_data = user_sequence_data[chat_id]
        seq_data["date"] = date_text
        seq_data["parsed_date"] = parsed_date
        seq_data["current_step"] = "time"
        user_states[chat_id] = STATE_SEQUENCE_WAITING_FOR_TIME
        
        await update.message.reply_text(f"✅ Date set: {date_text}\n\n⏰ Now send the time (e.g., 14:30 or 2:30 PM):")
        
    except ValueError:
        await update.message.reply_text("❌ Invalid date format. Please use DD-MM-YYYY (e.g., 12-08-2025):")

async def handle_sequence_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle time input for sequence"""
    chat_id = update.effective_chat.id
    time_text = update.message.text.strip()
    
    try:
        from datetime import datetime
        import pytz
        
        # Parse time in multiple formats
        time_formats = ["%H:%M", "%I:%M %p", "%I:%M%p"]
        parsed_time = None
        
        for fmt in time_formats:
            try:
                parsed_time = datetime.strptime(time_text.upper(), fmt).time()
                break
            except ValueError:
                continue
        
        if not parsed_time:
            await update.message.reply_text("❌ Invalid time format. Please use HH:MM or HH:MM AM/PM (e.g., 14:30 or 2:30 PM):")
            return
        
        seq_data = user_sequence_data[chat_id]
        seq_data["time"] = time_text
        seq_data["parsed_time"] = parsed_time
        
        # Combine date and time
        IST = pytz.timezone("Asia/Kolkata")
        combined_datetime = datetime.combine(seq_data["parsed_date"].date(), parsed_time)
        seq_data["scheduled_datetime"] = IST.localize(combined_datetime)
                
        # Now start browsing for first quiz
        seq_data["current_step"] = "select_first_quiz"
        user_states[chat_id] = None
        
        root_folder_id = '1xZNjra8vnE0v2JFpZtqUeB1qVpQlOuiQ'
        user_folder_stack[chat_id] = [root_folder_id]
        
        await update.message.reply_text(
            f"✅ Time set: {time_text}\n\n"
            f"📂 Now browse folders to select your *1st quiz file*:"
        )
        
        # Send folder browsing interface
        await list_drive_contents(update, context, root_folder_id)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error processing time: {e}")

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answers for leaderboard tracking"""
    try:
        poll_answer = update.poll_answer
        user = poll_answer.user
        
        poll_id = poll_answer.poll_id
        user_id = user.id
        username = user.username
        first_name = user.first_name
        last_name = user.last_name
        option_ids = poll_answer.option_ids
                
        handle_poll_answer_tracking(
            poll_id=poll_id,
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            selected_options=option_ids
        )
        
    except Exception as e:
        print(f"❌ Error handling poll answer: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler for the bot"""
    print(f"Exception while handling an update: {context.error}")
    
    if "TimedOut" in str(context.error) or "ConnectTimeout" in str(context.error):
        print("Network timeout error - this is usually temporary")
        if update and hasattr(update, 'effective_user') and update.effective_user:
            try:
                if hasattr(update, 'message') and update.message:
                    await update.message.reply_text(
                        "⚠️ Network timeout occurred. Please try again in a moment."
                    )
                elif hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.answer(
                        "⚠️ Network timeout. Please try again.", show_alert=True
                    )
            except:
                print("Could not send timeout error message to user")
    else:
        print(f"Unhandled error: {type(context.error).__name__}: {context.error}")
        if update and hasattr(update, 'effective_user') and update.effective_user:
            try:
                if hasattr(update, 'message') and update.message:
                    await update.message.reply_text(
                        "❌ An error occurred. Please try again or contact support."
                    )
            except:
                print("Could not send error message to user")

async def send_bot_message(chat_id: int, message: str, parse_mode: str = None):
    """Helper function to send messages via the bot"""
    try:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode=parse_mode)
        return True
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

async def test_bot_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test the quiz delivery system immediately"""
    # Only allow in private chat
    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
        
    user_id = update.effective_user.id
    await update.message.reply_text("🧪 Testing quiz delivery system...")
    
    success = test_notification(user_id)
    
    if success:
        await update.message.reply_text("✅ Quiz delivery system started! You should receive a quiz session shortly.")
    else:
        await update.message.reply_text("❌ Quiz delivery system failed - check if any .json quiz files exist")

async def test_sample_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test with the IVC.json file specifically"""
    # Only allow in private chat
    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
        
    user_id = update.effective_user.id
    
    if not os.path.exists("IVC.json"):
        await update.message.reply_text("❌ IVC.json file not found. Please ensure quiz files are available.")
        return
    
    await update.message.reply_text("🎯 Starting IVC quiz test session...")
    
    from SchedulerManager import send_scheduled_notification_sync
    success = send_scheduled_notification_sync(user_id, "IVC.json", "Test Session")
    
    if success:
        await update.message.reply_text("✅ IVC quiz session initiated!")
    else:
        await update.message.reply_text("❌ Failed to start quiz session")

async def check_failed_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to check failed notifications"""
    # Only allow in private chat
    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
        
    user_id = update.effective_user.id
    
    admin_ids = [7060447689]
    
    if user_id not in admin_ids:
        await update.message.reply_text("❌ Admin access required")
        return
    
    failed_notifications = get_failed_notifications()
    
    if not failed_notifications:
        await update.message.reply_text("✅ No failed notifications found!")
        return
    
    message = "💀 *Failed Notifications:*\n\n"
    for i, notification in enumerate(failed_notifications[:10], 1):  
        chat_id, file_name, formatted_time, failed_at = notification[1:5]
        message += f"{i}. Chat ID: {chat_id}\n"
        message += f"   File: {file_name}\n"
        message += f"   Time: {formatted_time}\n"
        message += f"   Failed: {failed_at}\n\n"
    
    if len(failed_notifications) > 10:
        message += f"... and {len(failed_notifications) - 10} more"
    
    await update.message.reply_text(message, parse_mode="MarkdownV2")

async def set_users_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the Google Drive file ID for users.json"""

    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /set_users_file <google_drive_file_id>")
        return
    
    file_id = context.args[0]
    leaderboard_manager.users_file_id = file_id
    
    await update.message.reply_text(f"✅ Users file ID set to: {file_id}")
    
    success = leaderboard_manager.download_users_file()
    if success:
        await update.message.reply_text("✅ Successfully downloaded users.json from Google Drive")
    else:
        await update.message.reply_text("⚠️ Could not download users.json - file may not exist yet")


async def set_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the group ID where quizzes will be posted"""
    # Only allow in private chat
    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
    
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "📢 To set your quiz group:\n\n"
            "1. Add me to your group\n"
            "2. Make me an admin (so I can send polls)\n"
            "3. In the group, forward any message to me\n"
            "4. Or use: /set_group <group_id>\n\n"
            "💡 You can also send me the group ID directly:"
        )
        user_states[user_id] = STATE_WAITING_FOR_GROUP_ID
        return
    
    try:
        group_id = int(context.args[0])
        user_group_ids[user_id] = group_id
        save_group_ids()  # Save to file
        
        # Test if bot can send to the group
        try:
            await bot.send_message(
                chat_id=group_id,
                text="✅ Quiz bot connected! Quizzes will be posted here.\n\nℹ️ All quiz management (scheduling, browsing files) happens in private chat with the bot."
            )
            await update.message.reply_text(f"✅ Group ID set successfully: {group_id}\n\n📋 Your scheduled quizzes will now be posted in this group!")
        except Exception as e:
            await update.message.reply_text(f"❌ Cannot send messages to group {group_id}. Make sure:\n• I'm added to the group\n• I have admin permissions\n• Group ID is correct")
            
    except ValueError:
        await update.message.reply_text("❌ Invalid group ID. Please provide a valid number.")


async def get_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get the current group ID setting"""
    # Only allow in private chat
    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
    
    user_id = update.effective_user.id
    group_id = user_group_ids.get(user_id)
    
    if group_id:
        await update.message.reply_text(f"📢 Your quiz group ID: {group_id}\n\n🔄 Use /set_group to change it")
    else:
        await update.message.reply_text("❌ No group ID set.\n\n📢 Use /set_group to configure where quizzes should be posted.")


async def set_users_file_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set the Google Drive file ID for users.json"""
    # Only allow in private chat
    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /set_users_file <google_drive_file_id>")
        return
    
    file_id = context.args[0]
    leaderboard_manager.users_file_id = file_id
    
    await update.message.reply_text(f"✅ Users file ID set to: {file_id}")
    
    success = leaderboard_manager.download_users_file()
    if success:
        await update.message.reply_text("✅ Successfully downloaded users.json from Google Drive")
    else:
        await update.message.reply_text("⚠️ Could not download users.json - file may not exist yet")


async def test_leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test leaderboard functionality"""

    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
        
    chat_id = update.effective_chat.id
    
    leaderboard_manager.start_quiz_session(chat_id, "Test Quiz", 3)
    
    leaderboard_manager.record_poll_answer(chat_id, 123, "testuser", "Test", "User", True, 1)
    leaderboard_manager.record_poll_answer(chat_id, 123, "testuser", "Test", "User", False, 2)
    leaderboard_manager.record_poll_answer(chat_id, 456, "anotheruser", "Another", "User", True, 1)
    leaderboard_manager.record_poll_answer(chat_id, 456, "anotheruser", "Another", "User", True, 2)
    
    leaderboard_msg = leaderboard_manager.generate_leaderboard(chat_id)
    
    if leaderboard_msg:
        # Send without markdown formatting to avoid parsing errors
        await update.message.reply_text(leaderboard_msg)
    else:
        await update.message.reply_text("❌ Failed to generate test leaderboard")
    
    leaderboard_manager.finish_quiz_session(chat_id)


async def get_chat_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get the chat ID - useful for finding group IDs"""
    chat_id = update.effective_chat.id
    chat_type = update.message.chat.type
    
    if chat_type == "private":
        await update.message.reply_text(f"📱 Your private chat ID: {chat_id}")
    elif chat_type in ["group", "supergroup"]:
        await update.message.reply_text(f"👥 This group's ID: {chat_id}")
    else:
        await update.message.reply_text(f"🆔 Chat ID: {chat_id}\n📍 Chat Type: {chat_type}")


async def test_group_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test if bot can access the hardcoded group"""
    # Only allow in private chat
    if update.message.chat.type != "private":
        await update.message.reply_text("⚠️ This command only works in private chat with the bot.")
        return
    
    await update.message.reply_text(f"🔍 Testing access to group ID: {HARDCODED_GROUP_ID}")
    
    try:
        # Try to get chat information
        chat_info = await bot.get_chat(HARDCODED_GROUP_ID)
        
        await update.message.reply_text(
            f"✅ Bot can access the group!\n\n"
            f"📊 Group Info:\n"
            f"• Title: {chat_info.title}\n"
            f"• Type: {chat_info.type}\n"
            f"• ID: {chat_info.id}\n"
            f"• Description: {chat_info.description or 'None'}"
        )
        
        # Try to send a test message
        try:
            test_msg = await bot.send_message(
                chat_id=HARDCODED_GROUP_ID,
                text="🧪 Bot access test - this message confirms the bot can post here!"
            )
            await update.message.reply_text("✅ Test message sent successfully to the group!")
        except Exception as send_error:
            await update.message.reply_text(
                f"⚠️ Can access group but cannot send messages:\n{send_error}\n\n"
                f"💡 Make sure bot has 'Send Messages' permission in the group."
            )
        
    except Exception as e:
        error_msg = str(e)
        
        if "chat not found" in error_msg.lower():
            await update.message.reply_text(
                f"❌ Group not found!\n\n"
                f"🔧 Troubleshooting steps:\n"
                f"1. Make sure bot is added to the group\n"
                f"2. Check if group ID is correct: {HARDCODED_GROUP_ID}\n"
                f"3. Use /get_chat_id in the group to verify ID\n"
                f"4. Make sure it's a supergroup (not regular group)\n\n"
                f"❓ Is this group ID correct?"
            )
        elif "forbidden" in error_msg.lower():
            await update.message.reply_text(
                f"❌ Access forbidden!\n\n"
                f"🔧 The bot is in the group but lacks permissions:\n"
                f"1. Make bot an admin in the group\n"
                f"2. Give it 'Send Messages' permission\n"
                f"3. Give it 'Send Polls' permission for quizzes\n\n"
                f"Error: {error_msg}"
            )
        else:
            await update.message.reply_text(f"❌ Unexpected error: {error_msg}")

async def test_scheduled_execution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test exactly what happens during scheduled execution - mimics the scheduler path"""
    if update.effective_chat.type != "private":
        return
    
    user_id = update.effective_user.id
    
    await update.message.reply_text("🔍 Testing scheduled execution path...\n\nThis will mimic exactly what happens when a scheduled quiz runs.")
    
    # Import the exact function that scheduled jobs use
    try:
        from SchedulerManager import send_scheduled_notification_sync
        
        # Test with a dummy file (we'll create one for testing)
        test_file_name = "test_quiz_file.json"
        formatted_time = "Test Time"
        timer_seconds = 10
        
        await update.message.reply_text(
            f"📤 Calling send_scheduled_notification_sync with:\n"
            f"• User ID: {user_id}\n"
            f"• File: {test_file_name}\n"
            f"• Timer: {timer_seconds}s\n\n"
            f"🎯 This will try to post to group: {HARDCODED_GROUP_ID}"
        )
        
        # Create a minimal test quiz file
        test_quiz = {
            "title": "🧪 Scheduled Execution Test",
            "questions": [
                {
                    "question": "This is a test question from scheduled execution path",
                    "options": ["Test Option 1", "Test Option 2"],
                    "correct": 0,
                    "explanation": "This is just a test"
                }
            ]
        }
        
        # Write test file
        import json
        import os
        file_path = os.path.join(os.getcwd(), test_file_name)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(test_quiz, f, indent=2)
            
        await update.message.reply_text("✅ Created test quiz file. Now calling scheduled delivery function...")
        
        # Call the exact same function that scheduler calls
        success = send_scheduled_notification_sync(user_id, test_file_name, formatted_time, timer_seconds)
        
        if success:
            await update.message.reply_text("✅ Scheduled execution test PASSED! The quiz should have been posted to the group.")
        else:
            await update.message.reply_text("❌ Scheduled execution test FAILED! This explains why your scheduled quizzes aren't working.")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error during scheduled execution test:\n{e}")

async def handle_quiz_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quiz type selection (single vs sequence)"""
    query = update.callback_query
    await query.answer()
    
    # Get chat_id safely
    try:
        chat_id = update.effective_chat.id
    except:
        chat_id = query.message.chat.id
        
    quiz_type = query.data.split("_")[2]  # single or sequence
    
    if quiz_type == "single":
        # Continue with normal single quiz flow
        user_states[chat_id] = STATE_WAITING_FOR_DATE
        await query.edit_message_text("📅 Send the date to schedule (e.g., 12-08-2025):")
        
    elif quiz_type == "sequence":
        # Start sequence flow - ask for timer of first quiz
        if chat_id not in user_sequence_data:
            user_sequence_data[chat_id] = {
                "quizzes": [],
                "current_step": "first_quiz_timer"
            }
        
        # Store first quiz info
        file_selection = user_file_selection.get(chat_id, {})
        user_sequence_data[chat_id]["temp_quiz"] = {
            "file_id": file_selection.get("file_id"),
            "file_name": file_selection.get("file_name"),
            "folder_id": file_selection.get("folder_id")
        }
        
        user_states[chat_id] = STATE_SEQUENCE_WAITING_FOR_QUIZ_TIMER
        await query.edit_message_text(
            f"� *Creating Quiz Sequence*\n\n"
            f"✅ First quiz: {file_selection.get('file_name', 'Unknown')}\n\n"
            f"⏱️ Enter timer seconds per question for this quiz (5-300):"
        )

async def handle_sequence_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sequence-related callbacks"""
    query = update.callback_query
    await query.answer()
    
    try:
        chat_id = update.effective_chat.id
    except:
        chat_id = query.message.chat.id
        
    callback_data = query.data
    
    if callback_data.startswith("gap_"):
        gap_minutes = int(callback_data.split("_")[1])
        
        if chat_id in user_sequence_data:
            seq_data = user_sequence_data[chat_id]
            
            if seq_data.get("current_step") == "first_gap":
                # First gap - add first quiz to sequence and browse for 2nd quiz
                current_quiz = seq_data["temp_quiz"]
                current_quiz["gap_minutes"] = gap_minutes
                seq_data["quizzes"].append(current_quiz)
                
                seq_data["current_step"] = "select_next_quiz"
                
                root_folder_id = '1xZNjra8vnE0v2JFpZtqUeB1qVpQlOuiQ'
                user_folder_stack[chat_id] = [root_folder_id]
                
                await query.edit_message_text(
                    f"✅ *Gap after Quiz 1:* {gap_minutes} minutes\n\n"
                    f"📂 Now browse folders to select your *2nd quiz file*:"
                )
                
                # Send folder browsing interface
                await list_drive_contents_for_callback(query, context, root_folder_id)
                
            elif seq_data.get("current_step") == "next_gap":
                # Gap for subsequent quiz - ask for next quiz
                # First update the last quiz with gap time
                if seq_data["quizzes"]:
                    seq_data["quizzes"][-1]["gap_minutes"] = gap_minutes
                
                quiz_count = len(seq_data["quizzes"])
                
                seq_data["current_step"] = "select_next_quiz"
                
                root_folder_id = '1xZNjra8vnE0v2JFpZtqUeB1qVpQlOuiQ'
                user_folder_stack[chat_id] = [root_folder_id]
                
                await query.edit_message_text(
                    f"✅ *Gap after Quiz {quiz_count}:* {gap_minutes} minutes\n\n"
                    f"� Now browse folders to select your *Quiz {quiz_count + 1} file*:"
                )
                
                # Send folder browsing interface  
                await list_drive_contents_for_callback(query, context, root_folder_id)
    
    elif callback_data == "seq_add_more":
        # Add more quiz to sequence - first ask for gap time
        seq_data = user_sequence_data[chat_id]
        if len(seq_data["quizzes"]) >= 10:
            await query.edit_message_text("❌ Maximum 10 quizzes allowed in a sequence!")
            return
        
        quiz_count = len(seq_data["quizzes"])
        seq_data["current_step"] = "next_gap"
        
        from SequenceManager import get_gap_time_keyboard
        keyboard = get_gap_time_keyboard()
        
        await query.edit_message_text(
            f"⏳ Select gap time before *Quiz {quiz_count + 1}*:",
            reply_markup=keyboard
        )
    
    elif callback_data == "seq_confirm":
        # Confirm and schedule sequence
        await confirm_sequence_schedule(update, context)

async def confirm_sequence_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and schedule the sequence"""
    query = update.callback_query
    
    # Get chat_id safely
    try:
        chat_id = update.effective_chat.id
    except:
        chat_id = query.message.chat.id
    
    if chat_id not in user_sequence_data:
        await query.edit_message_text("❌ No sequence data found!")
        return
    
    seq_data = user_sequence_data[chat_id]
    quizzes = seq_data["quizzes"]
    
    if len(quizzes) < 2:
        await query.edit_message_text("❌ Minimum 2 quizzes required for a sequence!")
        return
    
    # Import SequenceManager functions
    try:
        from SequenceManager import QuizSequence, save_sequence, execute_quiz_sequence
        from apscheduler.schedulers.background import BackgroundScheduler
        import pytz
        
        # Create sequence
        sequence_name = f"Quiz Sequence {datetime.now().strftime('%d-%m-%Y %H:%M')}"
        scheduled_time = seq_data["scheduled_datetime"]
        
        sequence = QuizSequence(chat_id, sequence_name, scheduled_time)
        
        # Add all quizzes to sequence
        for quiz in quizzes:
            sequence.add_quiz(
                quiz["file_name"],
                quiz["timer_seconds"], 
                quiz["gap_minutes"],
                quiz.get("file_id")
            )
        
        # Show preview
        preview_text = sequence.get_preview_text()
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"final_confirm_seq:{sequence.sequence_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_sequence")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Store sequence temporarily
        context.user_data[f"temp_sequence_{sequence.sequence_id}"] = sequence
        
        await query.edit_message_text(
            preview_text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2"
        )
        
    except Exception as e:
        await query.edit_message_text(f"❌ Error creating sequence: {e}")

async def handle_final_sequence_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle final sequence confirmation or cancellation"""
    query = update.callback_query
    await query.answer()
    
    # Get chat_id safely
    try:
        chat_id = update.effective_chat.id
    except:
        chat_id = query.message.chat.id
        
    callback_data = query.data
    
    if callback_data == "cancel_sequence":
        # Cancel sequence creation
        if chat_id in user_sequence_data:
            del user_sequence_data[chat_id]
        
        await query.edit_message_text("❌ Sequence creation cancelled.")
        return
    
    if callback_data.startswith("final_confirm_seq:"):
        # Final confirmation
        sequence_id = callback_data.split(":", 1)[1]
        temp_key = f"temp_sequence_{sequence_id}"
        
        if temp_key not in context.user_data:
            await query.edit_message_text("❌ Sequence data not found!")
            return
        
        sequence = context.user_data[temp_key]
        
        try:
            from SequenceManager import save_sequence, execute_quiz_sequence
            import pytz
            from apscheduler.schedulers.background import BackgroundScheduler
            
            service = authenticate()
            downloaded_files = []
            
            await query.edit_message_text("📥 Downloading quiz files...")
            
            # Import MediaIoBaseDownload here to avoid module loading issues
            from googleapiclient.http import MediaIoBaseDownload
            import io
            
            for i, quiz in enumerate(sequence.quizzes, 1):
                try:
                    # Get file_id from the quiz object
                    file_id = getattr(quiz, 'file_id', None)
                    
                    if file_id:
                        request = service.files().get_media(fileId=file_id)
                        file_path = os.path.join(os.getcwd(), quiz.file_name)
                        
                        with io.FileIO(file_path, 'wb') as fh:
                            downloader = MediaIoBaseDownload(fh, request)
                            done = False
                            while not done:
                                status, done = downloader.next_chunk()
                        
                        downloaded_files.append(quiz.file_name)
                    else:
                        # Fallback: search for file by name in Google Drive
                        print(f"⚠️ No file_id stored for {quiz.file_name}, searching...")
                        results = service.files().list(q=f"name='{quiz.file_name}'").execute()
                        files = results.get('files', [])
                        if files:
                            file_id = files[0]['id']
                            request = service.files().get_media(fileId=file_id)
                            file_path = os.path.join(os.getcwd(), quiz.file_name)
                            
                            with io.FileIO(file_path, 'wb') as fh:
                                downloader = MediaIoBaseDownload(fh, request)
                                done = False
                                while not done:
                                    status, done = downloader.next_chunk()
                            
                            downloaded_files.append(quiz.file_name)
                        else:
                            print(f"❌ Could not find file: {quiz.file_name}")
                            await query.edit_message_text(f"❌ Error: Could not find quiz file {i}: {quiz.file_name}\n\nPlease ensure all files exist in Google Drive.")
                            return
                        
                except Exception as e:
                    print(f"❌ Error downloading {quiz.file_name}: {e}")
                    await query.edit_message_text(f"❌ Error downloading quiz file {i}: {quiz.file_name}\n\nError: {e}")
                    return
            
            await query.edit_message_text(f"✅ Downloaded {len(downloaded_files)} quiz files. Scheduling sequence...")
            
            # Add downloaded files to sequence
            sequence.downloaded_files = downloaded_files
            
            # Save sequence to database
            save_sequence(sequence)
            
            # Schedule the sequence execution
            IST = pytz.timezone("Asia/Kolkata")
            # sequence.scheduled_time is already timezone-aware (IST)
            dt_utc = sequence.scheduled_time.astimezone(pytz.UTC)
            
            scheduler.add_job(
                execute_quiz_sequence,
                'date',
                run_date=dt_utc,
                args=[sequence.sequence_id],
                id=f"seq_{sequence.sequence_id}",
                misfire_grace_time=300,
                coalesce=True
            )
            
            # Clean up
            del context.user_data[temp_key]
            if chat_id in user_sequence_data:
                del user_sequence_data[chat_id]
            
            await query.edit_message_text(
                f"✅ *Sequence Scheduled Successfully\\!*\n\n"
                f"🎯 *{escape_markdown_v2(sequence.sequence_name)}*\n"
                f"📅 *Start Time:* {escape_markdown_v2(sequence.scheduled_time.strftime('%d %B %Y, %I:%M %p'))} IST\n"
                f"📊 *Total Quizzes:* {len(sequence.quizzes)}\n\n"
                f"🎮 Your quiz sequence will start automatically at the scheduled time\\!\n"
                f"📱 Use /sequences to view all your scheduled sequences\\.",
                parse_mode="MarkdownV2"
            )
            
        except Exception as e:
            await query.edit_message_text(f"❌ Error scheduling sequence: {e}")

async def list_sequences(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List user's scheduled sequences"""
    if update.effective_chat.type != "private":
        return
    
    user_id = update.effective_user.id
    
    try:
        from SequenceManager import get_user_sequences
        sequences = get_user_sequences(user_id)
        
        if not sequences:
            await update.message.reply_text("📋 You have no scheduled sequences.")
            return
        
        message = "📋 *Your Scheduled Sequences:*\n\n"
        
        for i, seq in enumerate(sequences[:10], 1):  # Limit to 10
            status_emoji = {
                "scheduled": "⏰",
                "running": "▶️", 
                "paused": "⏸️",
                "completed": "✅",
                "cancelled": "❌"
            }.get(seq["status"], "❓")
            
            message += f"{status_emoji} *{escape_markdown_v2(seq['name'])}*\n"
            message += f"   📅 {escape_markdown_v2(seq['scheduled_time'])}\n"
            message += f"   Status: {escape_markdown_v2(seq['status'].title())}\n\n"
        
        await update.message.reply_text(message, parse_mode="MarkdownV2")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error loading sequences: {e}")

async def pause_sequence_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause a running sequence"""
    if update.effective_chat.type != "private":
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /pause_sequence <sequence_id>")
        return
    
    sequence_id = context.args[0]
    
    try:
        from SequenceManager import pause_sequence
        success = pause_sequence(sequence_id)
        
        if success:
            await update.message.reply_text(f"⏸️ Sequence paused: {sequence_id}")
        else:
            await update.message.reply_text(f"❌ Could not pause sequence: {sequence_id}")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error pausing sequence: {e}")

async def resume_sequence_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume a paused sequence"""
    if update.effective_chat.type != "private":
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /resume_sequence <sequence_id>")
        return
    
    sequence_id = context.args[0]
    
    try:
        from SequenceManager import resume_sequence
        success = resume_sequence(sequence_id)
        
        if success:
            await update.message.reply_text(f"▶️ Sequence resumed: {sequence_id}")
        else:
            await update.message.reply_text(f"❌ Could not resume sequence: {sequence_id}")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error resuming sequence: {e}")

async def send_quiz_notification(chat_id: int, quiz_data: dict):
    """Send a quiz notification message"""
    try:
        message = f"🎯 *Quiz Time!*\n\n"
        message += f"📚 Quiz: {quiz_data.get('title', 'Untitled Quiz')}\n"
        message += f"📊 Questions: {len(quiz_data.get('questions', []))}\n"
        message += f"⏰ Ready to start your scheduled quiz!"
        
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="MarkdownV2"
        )
        return True
    except Exception as e:
        print(f"Error sending quiz notification: {e}")
        return False

def get_user_group_id(user_id: int) -> int:
    """Get the hardcoded group ID for quiz delivery"""
    return HARDCODED_GROUP_ID

def get_bot():
    """Get the bot instance for external use"""
    return bot

# Removed setup call - handlers are now set up in get_application()

def main():
    """Main function to start the bot with webhook"""
    print("Quiz Bot starting with webhook...")
    
    # Set up webhook URL (Render will provide this)
    webhook_url = os.environ.get('RENDER_EXTERNAL_URL', 'https://timer-quiz-y7gc.onrender.com')
    webhook_path = f"{webhook_url}/webhook"
    
    # Get the application instance (this will create it if needed)
    app = get_application()
    
    # Initialize the application
    try:
        # Set webhook
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def set_webhook():
            await app.bot.set_webhook(webhook_path)
            print(f"✅ Webhook set to: {webhook_path}")
            
        loop.run_until_complete(set_webhook())
        loop.close()
        
    except Exception as e:
        print(f"❌ Error setting webhook: {e}")
    
    print("🌐 Bot ready to receive webhooks via Flask app")

# For local development, you can still use polling
def main_polling():
    """Alternative main function for local development with polling"""
    print("Quiz Bot starting with polling (local development)...")
    app = get_application()
    app.run_polling()

if __name__ == "__main__":
    # Use polling for local development
    main_polling()
# Note: For production (Gunicorn), webhook setup happens when first webhook request is received