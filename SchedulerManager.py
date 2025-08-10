import json
import uuid
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.base import JobLookupError
import pytz
import asyncio
import sqlite3
import os
import time
import requests
from LeaderboardManager import leaderboard_manager

# Import function to get user's group ID
HARDCODED_GROUP_ID = -1002526503801  # Direct hardcoded group ID to avoid circular imports

try:
    from BrowseFile import get_user_group_id
except ImportError:
    # Fallback if import fails - use hardcoded group ID
    def get_user_group_id(user_id: int) -> int:
        return HARDCODED_GROUP_ID

IST = pytz.timezone("Asia/Kolkata")

jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///schedules.db')
}
executors = {
    'default': ThreadPoolExecutor(20)
}
job_defaults = {
    'coalesce': False,
    'max_instances': 3
}

scheduler = BackgroundScheduler(jobstores=jobstores, executors=executors, job_defaults=job_defaults)
scheduler.start()

DATABASE_FILE = "schedules.db"

_bot_instance = None

active_polls = {}

def set_bot_instance(bot):
    """Set the bot instance from BrowseFile.py"""
    global _bot_instance
    _bot_instance = bot

def get_bot_instance():
    """Get the bot instance"""
    return _bot_instance

def init_database():
    """Initialize SQLite database for schedule metadata"""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            downloaded_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            timer_seconds INTEGER DEFAULT 10
        )
    ''')
    conn.commit()
    conn.close()

def load_schedules():
    """Load all schedules from SQLite database"""
    init_database()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM schedules ORDER BY scheduled_at')
    rows = cursor.fetchall()
    conn.close()
    
    schedules = []
    for row in rows:
        schedules.append({
            "id": row[0],
            "file_id": row[1],
            "file_name": row[2],
            "file_path": row[3],
            "scheduled_at": row[4],
            "created_by": row[5],
            "downloaded_at": row[6],
            "status": row[7] if len(row) > 7 else 'pending',
            "timer_seconds": row[8] if len(row) > 8 else 10
        })
    return schedules

def save_schedule(schedule):
    """Save a single schedule to SQLite database"""
    init_database()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO schedules 
        (id, file_id, file_name, file_path, scheduled_at, created_by, downloaded_at, status, timer_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        schedule["id"],
        schedule["file_id"], 
        schedule["file_name"],
        schedule["file_path"],
        schedule["scheduled_at"],
        schedule["created_by"],
        schedule["downloaded_at"],
        schedule.get("status", "pending"),
        schedule.get("timer_seconds", 10)
    ))
    conn.commit()
    conn.close()

def add_schedule(file_id, file_name, path, date_str, time_str, user_id, timer_seconds=10):
    dt = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M")
    dt_ist = IST.localize(dt)
    dt_utc = dt_ist.astimezone(pytz.utc)

    schedule_id = str(uuid.uuid4())[:8]
    schedule = {
        "id": schedule_id,
        "file_id": file_id,
        "file_name": file_name,
        "file_path": path,
        "scheduled_at": dt_utc.isoformat(),
        "created_by": user_id,
        "downloaded_at": datetime.now().isoformat(),
        "status": "pending",
        "timer_seconds": timer_seconds
    }

    save_schedule(schedule)

    scheduler.add_job(
        send_notification_with_retry,
        'date',
        run_date=dt_utc,
        args=[user_id, file_name, dt_ist.strftime("%d %B %Y, %I:%M %p"), timer_seconds],
        id=schedule_id,
        misfire_grace_time=300,
        coalesce=True
    )

    return schedule

def send_scheduled_notification_sync(chat_id: int, file_name: str, formatted_time: str, timer_seconds: int = 10):
    """Production-grade synchronous notification using HTTP requests"""
    
    # Get user's group ID - always use hardcoded group ID
    group_id = get_user_group_id(chat_id)
    target_chat_id = group_id
    
    bot = get_bot_instance()
    if not bot:
        print("❌ Bot instance not available")
        return False
    
    try:
        import requests
        import json as json_lib
        
        bot_token = None
        if hasattr(bot, '_token'):
            bot_token = bot._token
        elif hasattr(bot, 'token'):
            bot_token = bot.token
        else:
            try:
                from BrowseFile import BOT_TOKEN
                bot_token = BOT_TOKEN
            except:
                print("❌ Could not retrieve bot token")
                return False
        
        if not bot_token:
            print("❌ Bot token not available")
            return False
        
        quiz_data = load_quiz_file(file_name)
        if not quiz_data:
            print(f"❌ Could not load quiz file: {file_name}")
            return False
        
        success = deliver_quiz_session(target_chat_id, quiz_data, bot_token, timer_seconds, chat_id)
        
        if success:            
            try:
                file_path = os.path.join(os.getcwd(), file_name)
                if os.path.exists(file_path):
                    os.remove(file_path)
                else:
                    print(f"⚠️ Quiz file not found for deletion: {file_path}")
            except Exception as e:
                print(f"❌ Error deleting quiz file {file_name}: {e}")
            
            update_schedule_status(chat_id, file_name, "completed")
            return True
        else:
            print(f"❌ Failed to start quiz session for {chat_id}")
            return False
            
    except Exception as e:
        print(f"❌ Unexpected error starting quiz for {chat_id}: {e}")
        return False

def load_quiz_file(file_name: str):
    """Load quiz data from downloaded JSON file"""
    try:
        file_path = os.path.join(os.getcwd(), file_name)
        if not os.path.exists(file_path):
            print(f"❌ Quiz file not found: {file_path}")
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            quiz_data = json.load(f)
        return quiz_data
        
    except Exception as e:
        print(f"❌ Error loading quiz file {file_name}: {e}")
        return None

def deliver_quiz_session(chat_id: int, quiz_data: dict, bot_token: str, timer_seconds: int = 10, user_id: int = None):
    """Deliver the complete quiz session with questions, polls, explanations, and leaderboard
    
    Args:
        chat_id: Where to send the quiz (group or private chat)
        quiz_data: Quiz data from JSON
        bot_token: Bot token for API calls
        timer_seconds: Timer per question
        user_id: Original user ID for leaderboard tracking (if different from chat_id)
    """
    import threading
    import time
    
    # Use chat_id for leaderboard if user_id not provided (backward compatibility)
    leaderboard_chat_id = user_id if user_id else chat_id
    
    def run_quiz():
        try:
            quiz_title = quiz_data.get('title', 'Quiz Session')
            questions = quiz_data.get('questions', [])
            
            if not questions:
                send_message_with_retry(bot_token, chat_id, "❌ No questions found in this quiz.")
                return
            
            leaderboard_manager.start_quiz_session(leaderboard_chat_id, quiz_title, len(questions))
            
            start_message = f"🎯 {quiz_title}\n\n📊 Total Questions: {len(questions)}\n⏰ Timer: {timer_seconds} seconds per question\n🎮 Let's begin!"
            send_message_with_retry(bot_token, chat_id, start_message)
            
            # If quiz is posted in a group, notify the user in private chat
            if user_id and user_id != chat_id:
                try:
                    private_notification = f"🎯 Your scheduled quiz '{quiz_title}' has started in the group!\n\n📊 Questions: {len(questions)}\n⏰ Timer: {timer_seconds}s per question"
                    send_message_with_retry(bot_token, user_id, private_notification, max_retries=2)
                except Exception as e:
                    print(f"⚠️ Could not send private notification to user {user_id}: {e}")
            
            time.sleep(2)
            
            for i, question_data in enumerate(questions, 1):
                
                success = deliver_single_question(
                    chat_id, question_data, i, len(questions), bot_token, timer_seconds, leaderboard_chat_id
                )
                
                if not success:
                    print(f"❌ Failed to deliver question {i}")
                    break
                
                time.sleep(1)
            
            # Generate and send leaderboard - ALWAYS try to show results
            leaderboard_msg = leaderboard_manager.generate_leaderboard(leaderboard_chat_id)
            
            if leaderboard_msg:
                # Try to send leaderboard with retry mechanism
                leaderboard_sent = False
                for attempt in range(3):  # Try 3 times with simple text
                    try:
                        leaderboard_response = send_message_with_retry(bot_token, chat_id, leaderboard_msg, None)  # No markdown
                        if leaderboard_response:
                            leaderboard_sent = True
                            break
                        else:
                            print(f"⚠️ Leaderboard send attempt {attempt + 1} failed")
                    except Exception as e:
                        print(f"❌ Leaderboard send attempt {attempt + 1} error: {e}")
                    
                    if attempt < 2:  # Wait before retry
                        time.sleep(2)
                
                # If all attempts failed, send a simple summary
                if not leaderboard_sent:
                    try:
                        session_stats = leaderboard_manager.get_quiz_stats(leaderboard_chat_id)
                        participants = session_stats.get("participants", {})
                        simple_summary = f"📊 Quiz Complete!\n\nParticipants: {len(participants)}\n"
                        if participants:
                            simple_summary += "\nTop performer:\n"
                            # Find best performer
                            best_participant = max(participants.items(), key=lambda x: x[1]["correct_answers"])
                            simple_summary += f"🏆 {best_participant[1]['name']}: {best_participant[1]['correct_answers']} correct"
                        
                        send_message_with_retry(bot_token, chat_id, simple_summary, None)
                    except Exception as e:
                        print(f"❌ Even simple summary failed: {e}")
                        # Last resort - just confirm quiz completion
                        try:
                            send_message_with_retry(bot_token, chat_id, "🎉 Quiz completed! Results were processed.", None)
                        except:
                            pass
            else:
                print("⚠️ No leaderboard data generated - sending completion message")
                send_message_with_retry(bot_token, chat_id, "🎉 Quiz completed! Thank you for participating.", None)
            
            # Finish session and upload user data
            upload_success = leaderboard_manager.finish_quiz_session(leaderboard_chat_id)
            if upload_success:
                pass
            else:
                print("⚠️ Failed to upload user data to Google Drive")
                
        except Exception as e:
            print(f"❌ Error in quiz delivery thread: {e}")
    
    # Run quiz in background thread
    quiz_thread = threading.Thread(target=run_quiz)
    quiz_thread.daemon = True
    quiz_thread.start()
    
    return True

def escape_markdown_v2(text):
    """Escape special characters for MarkdownV2"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def deliver_single_question(chat_id: int, question_data: dict, question_num: int, total_questions: int, bot_token: str, timer_seconds: int = 10, leaderboard_chat_id: int = None):
    """Deliver a single question with poll and explanation
    
    Args:
        chat_id: Where to send the question (group or private chat)
        question_data: Question data from JSON
        question_num: Current question number
        total_questions: Total questions count
        bot_token: Bot token for API calls
        timer_seconds: Timer per question
        leaderboard_chat_id: Chat ID for leaderboard tracking (if different from chat_id)
    """
    import time
    
    # Use chat_id for leaderboard if not provided
    if leaderboard_chat_id is None:
        leaderboard_chat_id = chat_id
    
    try:
        question_text = question_data.get('question', 'No question text')
        options = question_data.get('options', [])
        correct_index = question_data.get('correct', 0)
        explanation = question_data.get('explanation', 'No explanation provided')
        
        if len(options) < 2:
            print(f"❌ Question {question_num} has insufficient options")
            return False
        
        options = options[:10]
        
        question_message = f"*Question {question_num}/{total_questions}*\n\n"
        question_message += f"{escape_markdown_v2(question_text)}\n\n"
        
        option_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']
        for idx, option in enumerate(options):
            question_message += f"*{option_letters[idx]}\\.* {escape_markdown_v2(option)}\n"
        
        question_msg_response = send_message_with_retry(bot_token, chat_id, question_message, "MarkdownV2")
        if not question_msg_response:
            print(f"❌ Failed to send question {question_num}")
            return False
        
        question_message_id = question_msg_response.get('result', {}).get('message_id')
        
        time.sleep(1)

        poll_question = f"Q{question_num}: Choose your answer"
        poll_options = [option_letters[idx] for idx in range(len(options))]  
        
        if correct_index >= len(options):
            correct_index = 0
            print(f"⚠️ Corrected invalid answer index for question {question_num}")
        
        poll_response = send_poll_with_retry(
            bot_token, chat_id, poll_question, poll_options,
            correct_option_id=correct_index, open_period=timer_seconds
        )
        
        if not poll_response:
            print(f"❌ Failed to send poll for question {question_num}")
            return False
        
        # Track poll for leaderboard
        poll_id = poll_response.get('result', {}).get('poll', {}).get('id')
        if poll_id:
            # Use leaderboard_chat_id if provided, otherwise fallback to chat_id
            tracking_chat_id = leaderboard_chat_id if leaderboard_chat_id else chat_id
            active_polls[poll_id] = {
                'chat_id': tracking_chat_id,  # Use appropriate chat_id for tracking
                'question_num': question_num,
                'correct_option': correct_index,
                'quiz_title': question_data.get('quiz_title', 'Quiz'),
                'question_text': question_text[:50] + "..." if len(question_text) > 50 else question_text
            }        

        time.sleep(timer_seconds + 2)
        
        if poll_id:
            cleanup_poll_tracking(poll_id)
        
        explanation_message = question_message + f"\n\n💡 *Explanation:*\n{escape_markdown_v2(explanation)}"
        
        edit_success = edit_message(bot_token, chat_id, question_message_id, explanation_message, "MarkdownV2")
        
        if edit_success:
            pass
        else:
            # If edit fails, send explanation as new message
            explanation_text = f"💡 *Explanation for Question {question_num}:*\n{escape_markdown_v2(explanation)}"
            send_message_with_retry(bot_token, chat_id, explanation_text, "MarkdownV2")
        
        # Brief pause before next question
        time.sleep(2)
        return True
        
    except Exception as e:
        print(f"❌ Error delivering question {question_num}: {e}")
        return False

def send_message_with_retry(bot_token: str, chat_id: int, text: str, parse_mode: str = None, max_retries: int = 5):
    """Production-grade message sending with exponential backoff and timeout handling"""
    for attempt in range(max_retries):
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text
            }
            
            if parse_mode:
                payload["parse_mode"] = parse_mode
            
            # Progressive timeout: 30s, 45s, 60s, 90s, 120s
            timeout = 30 + (attempt * 15)
            
            
            response = requests.post(url, json=payload, timeout=timeout)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    return result
                else:
                    print(f"❌ Telegram API error: {result.get('description', 'Unknown error')}")
            else:
                print(f"❌ HTTP {response.status_code}: {response.text}")
            
        except requests.exceptions.Timeout:
            print(f"⏰ Telegram server timeout on attempt {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                delay = 2 ** attempt  # Exponential backoff: 1, 2, 4, 8, 16 seconds
                print(f"⏳ Waiting {delay}s before retry due to server timeout...")
                time.sleep(delay)
            continue
            
        except requests.exceptions.RequestException as e:
            print(f"🌐 Network error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                delay = 2 ** attempt
                print(f"⏳ Waiting {delay}s before retry due to network error...")
                time.sleep(delay)
            continue
            
        except Exception as e:
            print(f"❌ Unexpected error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                delay = 2 ** attempt
                print(f"⏳ Waiting {delay}s before retry due to unexpected error...")
                time.sleep(delay)
            continue

        if attempt < max_retries - 1:
            delay = 2 ** attempt
            print(f"⏳ Waiting {delay}s before retry...")
            time.sleep(delay)
    
    # All retries failed
    print("💀 All message send attempts failed - notifying user about server issues")
    
    # Try to send a simple fallback message about server issues
    try:
        fallback_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        fallback_payload = {
            "chat_id": chat_id,
            "text": "⚠️ Telegram servers are experiencing delays. Your quiz is being processed but responses may be slow."
        }
        requests.post(fallback_url, json=fallback_payload, timeout=15)
    except:
        pass  # If even fallback fails, give up gracefully
        
    return None

def send_poll_with_retry(bot_token: str, chat_id: int, question: str, options: list, 
                        correct_option_id: int = None, open_period: int = 10, max_retries: int = 5):
    """Production-grade poll sending with retry logic and server delay handling"""
    for attempt in range(max_retries):
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendPoll"
            payload = {
                "chat_id": chat_id,
                "question": question,
                "options": options,
                "is_anonymous": False,
                "type": "quiz" if correct_option_id is not None else "regular",
                "open_period": open_period
            }
            
            if correct_option_id is not None:
                payload["correct_option_id"] = correct_option_id
                payload["explanation"] = "Answer revealed after timer!"
            
            # Progressive timeout for polls
            timeout = 40 + (attempt * 20)  # 40s, 60s, 80s, 100s, 120s
                        
            response = requests.post(url, json=payload, timeout=timeout)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    return result
                else:
                    error_desc = result.get('description', 'Unknown error')
                    print(f"❌ Telegram API error: {error_desc}")
                    
                    # Handle specific Telegram errors
                    if "FLOOD_WAIT" in error_desc:
                        # Extract wait time if available
                        wait_time = 60  # Default wait time
                        print(f"🚦 Rate limited - waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
            else:
                print(f"❌ HTTP {response.status_code}: {response.text}")
            
        except requests.exceptions.Timeout:
            print(f"⏰ Telegram server timeout for poll on attempt {attempt + 1}/{max_retries}")
            
            # Send immediate notification about delay
            try:
                delay_msg = f"⏱️ Quiz question is loading... Telegram servers are responding slowly. Please wait."
                send_message_with_retry(bot_token, chat_id, delay_msg, max_retries=2)
            except:
                pass
                
            if attempt < max_retries - 1:
                delay = 3 + (attempt * 2)  # 3, 5, 7, 9 seconds
                print(f"⏳ Waiting {delay}s before poll retry...")
                time.sleep(delay)
            continue
            
        except Exception as e:
            print(f"❌ Error sending poll on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                delay = 2 + attempt  # 2, 3, 4, 5 seconds
                time.sleep(delay)
            continue
        
        # If we get here, the request failed
        if attempt < max_retries - 1:
            delay = 2 + attempt
            print(f"⏳ Retrying poll in {delay}s...")
            time.sleep(delay)
    
    print("💀 Poll send failed completely - sending fallback text question")
    fallback_text = f"❓ {question}\n\nOptions:\n"
    for i, option in enumerate(options):
        fallback_text += f"{chr(65 + i)}. {option}\n"
    fallback_text += f"\n⏰ Timer: {open_period} seconds\n⚠️ Poll failed due to server issues - please answer in chat."
    
    send_message_with_retry(bot_token, chat_id, fallback_text, max_retries=3)
    return None

def edit_message(bot_token: str, chat_id: int, message_id: int, text: str, parse_mode: str = None):
    """Edit a message using Telegram Bot API"""
    import requests
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text
        }
        
        if parse_mode:
            payload["parse_mode"] = parse_mode
        
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                return True
        
        print(f"⚠️ Message edit failed (this is normal): {response.text}")
        return False
        
    except Exception as e:
        print(f"⚠️ Error editing message (this is normal): {e}")
        return False

def update_schedule_status(chat_id: int, file_name: str, status: str):
    """Update schedule status in database"""
    try:
        init_database()
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE schedules SET status = ? WHERE created_by = ? AND file_name = ?',
            (status, chat_id, file_name)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Error updating schedule status: {e}")

def send_notification_with_retry(chat_id: int, file_name: str, formatted_time: str, timer_seconds: int = 10, max_retries: int = 3):
    """Production-grade notification with exponential backoff retry - now handles quiz delivery"""
    import time
    
    for attempt in range(max_retries):
        
        success = send_scheduled_notification_sync(chat_id, file_name, formatted_time, timer_seconds)
        
        if success:
            return True
        
        if attempt < max_retries - 1:  # Don't sleep on last attempt
            # Exponential backoff: 2, 4, 8 seconds
            delay = 2 ** attempt
            print(f"⏳ Retrying quiz delivery in {delay} seconds...")
            time.sleep(delay)
    
    # All retries failed - log to dead letter queue
    print(f"💀 All quiz delivery retries failed for {chat_id}. Adding to dead letter queue.")
    log_failed_notification(chat_id, file_name, formatted_time)
    return False

def log_failed_notification(chat_id: int, file_name: str, formatted_time: str):
    """Log failed notifications for manual review"""
    try:
        init_database()
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # Create failed_notifications table if it doesn't exist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS failed_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                formatted_time TEXT NOT NULL,
                failed_at TEXT NOT NULL,
                retry_count INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            INSERT INTO failed_notifications (chat_id, file_name, formatted_time, failed_at)
            VALUES (?, ?, ?, ?)
        ''', (chat_id, file_name, formatted_time, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        print(f"📋 Failed notification logged to dead letter queue")
        
    except Exception as e:
        print(f"❌ Error logging failed notification: {e}")

def get_all_schedules_count():
    """Get total count of active schedules"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM schedules WHERE status = 'scheduled'")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        print(f"❌ Error getting schedule count: {e}")
        return 0

def get_failed_notifications():
    """Get all failed notifications for admin review"""
    try:
        init_database()
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM failed_notifications ORDER BY failed_at DESC')
        rows = cursor.fetchall()
        conn.close()
        return rows
    except:
        return []

def send_scheduled_notification(chat_id: int, file_name: str, formatted_time: str):
    """Legacy function - kept for compatibility"""
    send_scheduled_notification_sync(chat_id, file_name, formatted_time)

async def send_notification_async(chat_id: int, file_name: str, formatted_time: str):
    """Async function to send the actual notification"""
    try:
        bot = get_bot_instance()
        if not bot:
            print("Bot instance not available")
            return

        # Send notification
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ File *{file_name}* has been downloaded and is ready.\n⏰ Scheduled Time: *{formatted_time}*",
            parse_mode="Markdown"
        )
        print(f"Notification sent to {chat_id} for file: {file_name}")
    except Exception as e:
        # Just log the error, don't try to send another async message
        # This prevents the "Event loop is closed" error
        print(f"Failed to send notification to {chat_id}: {e}")
        print(f"Notification was for file: {file_name} at {formatted_time}")

def get_schedules_by_user(user_id):
    schedules = load_schedules()
    return [s for s in schedules if s["created_by"] == user_id]

def delete_schedule(schedule_id):
    """Delete schedule from both SQLite database and APScheduler"""
    init_database()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
    conn.commit()
    conn.close()

    try:
        scheduler.remove_job(schedule_id)
    except JobLookupError:
        pass

def edit_schedule(schedule_id, new_date, new_time):
    """Edit schedule in both SQLite database and APScheduler"""
    dt = datetime.strptime(f"{new_date} {new_time}", "%d-%m-%Y %H:%M")
    dt_ist = IST.localize(dt)
    dt_utc = dt_ist.astimezone(pytz.utc)
    
    # Update SQLite database
    init_database()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE schedules SET scheduled_at = ? WHERE id = ?', 
                   (dt_utc.isoformat(), schedule_id))
    conn.commit()
    conn.close()

    try:
        scheduler.reschedule_job(schedule_id, trigger='date', run_date=dt_utc)
    except JobLookupError:
        pass

def migrate_from_json():
    """Migrate existing schedules from JSON to SQLite (one-time migration)"""
    json_file = "schedules.json"
    if not os.path.exists(json_file):
        print("No JSON schedules file found - migration not needed")
        return
    
    print("Migrating schedules from JSON to SQLite...")
    
    try:
        with open(json_file, "r") as f:
            json_schedules = json.load(f)
        
        migrated_count = 0
        for schedule in json_schedules:
            save_schedule(schedule)
            migrated_count += 1
        
        
        # Backup the JSON file
        backup_name = f"schedules_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.rename(json_file, backup_name)
        print(f"📦 JSON file backed up as: {backup_name}")
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")

# Initialize database on import
init_database()

# Auto-migrate if JSON file exists
if os.path.exists("schedules.json"):
    migrate_from_json()

def test_notification(chat_id: int):
    """Test function to immediately send a quiz session"""
    print(f"🧪 Testing quiz delivery system for chat_id: {chat_id}")
    
    import os
    import glob
    
    json_files = glob.glob("*.json")
    test_files = [f for f in json_files if f not in ['schedules.json']]
    
    if not test_files:
        print("❌ No quiz JSON files found for testing")
        return False
    
    test_file = test_files[0]
    print(f"🎯 Using test file: {test_file}")
    
    success = send_scheduled_notification_sync(
        chat_id, 
        test_file, 
        "Test Session - Current Time",
        15  # Test with 15-second timer
    )
    
    if success:
        pass
    else:
        print("❌ Test quiz delivery failed")
    
    return success

def handle_poll_answer_tracking(poll_id: str, user_id: int, username: str, first_name: str, last_name: str, selected_options: list):
    """Handle poll answer for leaderboard tracking"""
    try:
        if poll_id not in active_polls:
            print(f"⚠️ Poll {poll_id} not found in active polls")
            return
        
        poll_info = active_polls[poll_id]
        chat_id = poll_info['chat_id']
        correct_option = poll_info['correct_option']
        question_num = poll_info['question_num']
        
        is_correct = len(selected_options) > 0 and selected_options[0] == correct_option
        
        leaderboard_manager.record_poll_answer(
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_correct=is_correct,
            question_number=question_num
        )
        
    except Exception as e:
        print(f"❌ Error tracking poll answer: {e}")

def cleanup_poll_tracking(poll_id: str):
    """Clean up poll tracking after timer expires"""
    try:
        if poll_id in active_polls:
            del active_polls[poll_id]
    except Exception as e:
        print(f"❌ Error cleaning up poll tracking: {e}")

def test_markdown_formatting():
    """Test function to validate MarkdownV2 formatting"""
    test_text = "Test message with special chars: . ! - + = | { } ( ) [ ] ~ ` > # _ * "
    escaped = escape_markdown_v2(test_text)
    print(f"Original: {test_text}")
    print(f"Escaped:  {escaped}")
    return escaped