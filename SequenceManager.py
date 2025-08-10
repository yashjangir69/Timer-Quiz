import json
import uuid
import sqlite3
import asyncio
import threading
import time
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Import existing managers
from SchedulerManager import send_scheduled_notification_sync, get_bot_instance
from LeaderboardManager import leaderboard_manager

IST = pytz.timezone("Asia/Kolkata")
DATABASE_FILE = "sequences.db"

# Active sequence tracking
active_sequences = {}
paused_sequences = set()

class SequenceQuiz:
    """Represents a single quiz in a sequence"""
    def __init__(self, file_name: str, timer_seconds: int, gap_minutes: int, file_id: str = None):
        self.file_name = file_name
        self.timer_seconds = timer_seconds
        self.gap_minutes = gap_minutes
        self.file_id = file_id  # Google Drive file ID
        self.status = "pending"  # pending, running, completed

class QuizSequence:
    """Represents a complete quiz sequence"""
    def __init__(self, user_id: int, sequence_name: str, scheduled_time: datetime):
        self.sequence_id = str(uuid.uuid4())
        self.user_id = user_id
        self.sequence_name = sequence_name
        self.scheduled_time = scheduled_time
        self.quizzes: List[SequenceQuiz] = []
        self.current_quiz_index = 0
        self.status = "scheduled"  # scheduled, running, paused, completed, cancelled
        self.created_at = datetime.now()

    def add_quiz(self, file_name: str, timer_seconds: int, gap_minutes: int, file_id: str = None):
        """Add a quiz to the sequence"""
        quiz = SequenceQuiz(file_name, timer_seconds, gap_minutes, file_id)
        self.quizzes.append(quiz)

    def get_preview_text(self) -> str:
        """Generate preview text for confirmation"""
        def escape_md(text):
            if not text:
                return text
            text = str(text)
            escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
            for char in escape_chars:
                text = text.replace(char, f'\\{char}')
            return text
        
        preview = f"🎯 *Sequence Preview: {escape_md(self.sequence_name)}*\n\n"
        preview += f"📅 *Start Time:* {escape_md(self.scheduled_time.strftime('%d %B %Y, %I:%M %p'))} IST\n"
        preview += f"📊 *Total Quizzes:* {len(self.quizzes)}\n\n"
        
        for i, quiz in enumerate(self.quizzes, 1):
            preview += f"*Quiz {i}:* {escape_md(quiz.file_name)}\n"
            preview += f"⏰ Timer: {quiz.timer_seconds}s per question\n"
            if i < len(self.quizzes):
                preview += f"⏳ Gap: {quiz.gap_minutes} minutes\n"
            preview += "\n"
        
        return preview

def init_sequence_database():
    """Initialize the sequence database"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sequences (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                sequence_name TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                status TEXT DEFAULT 'scheduled',
                created_at TEXT NOT NULL,
                sequence_data TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Error initializing sequence database: {e}")

def save_sequence(sequence: QuizSequence):
    """Save sequence to database"""
    try:
        init_sequence_database()
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # Convert sequence to JSON
        sequence_data = {
            'sequence_id': sequence.sequence_id,
            'user_id': sequence.user_id,
            'sequence_name': sequence.sequence_name,
            'scheduled_time': sequence.scheduled_time.isoformat(),
            'status': sequence.status,
            'created_at': sequence.created_at.isoformat(),
            'downloaded_files': getattr(sequence, 'downloaded_files', []),
            'quizzes': [
                {
                    'file_name': quiz.file_name,
                    'timer_seconds': quiz.timer_seconds,
                    'gap_minutes': quiz.gap_minutes,
                    'file_id': getattr(quiz, 'file_id', None),
                    'status': quiz.status
                }
                for quiz in sequence.quizzes
            ]
        }
        
        cursor.execute('''
            INSERT OR REPLACE INTO sequences 
            (id, user_id, sequence_name, scheduled_time, status, created_at, sequence_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            sequence.sequence_id,
            sequence.user_id,
            sequence.sequence_name,
            sequence.scheduled_time.isoformat(),
            sequence.status,
            sequence.created_at.isoformat(),
            json.dumps(sequence_data)
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error saving sequence: {e}")

def load_sequence(sequence_id: str) -> Optional[QuizSequence]:
    """Load sequence from database"""
    try:
        init_sequence_database()
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        cursor.execute('SELECT sequence_data FROM sequences WHERE id = ?', (sequence_id,))
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return None
            
        data = json.loads(result[0])
        
        # Reconstruct sequence object
        sequence = QuizSequence(
            data['user_id'],
            data['sequence_name'],
            datetime.fromisoformat(data['scheduled_time'])
        )
        sequence.sequence_id = data['sequence_id']
        sequence.status = data['status']
        sequence.created_at = datetime.fromisoformat(data['created_at'])
        sequence.downloaded_files = data.get('downloaded_files', [])
        
        # Reconstruct quizzes
        for quiz_data in data['quizzes']:
            quiz = SequenceQuiz(
                quiz_data['file_name'],
                quiz_data['timer_seconds'],
                quiz_data['gap_minutes'],
                quiz_data.get('file_id')
            )
            quiz.status = quiz_data['status']
            sequence.quizzes.append(quiz)
            
        return sequence
        
    except Exception as e:
        print(f"❌ Error loading sequence: {e}")
        return None

def get_gap_time_keyboard():
    """Create inline keyboard for gap time selection"""
    keyboard = [
        [
            InlineKeyboardButton("1 min", callback_data="gap_1"),
            InlineKeyboardButton("2 min", callback_data="gap_2"),
            InlineKeyboardButton("3 min", callback_data="gap_3")
        ],
        [
            InlineKeyboardButton("4 min", callback_data="gap_4"),
            InlineKeyboardButton("5 min", callback_data="gap_5")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_sequence_action_keyboard():
    """Create inline keyboard for sequence actions"""
    keyboard = [
        [
            InlineKeyboardButton("➕ Add More Quiz", callback_data="seq_add_more"),
            InlineKeyboardButton("✅ Confirm Schedule", callback_data="seq_confirm")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def cleanup_quiz_files(sequence):
    """Delete downloaded quiz files after sequence completion"""
    try:
        if hasattr(sequence, 'downloaded_files'):
            for file_name in sequence.downloaded_files:
                file_path = os.path.join(os.getcwd(), file_name)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"🗑️ Deleted: {file_name}")
                else:
                    print(f"⚠️ File not found for deletion: {file_name}")
            print(f"✅ Cleaned up {len(sequence.downloaded_files)} quiz files")
        else:
            print("ℹ️ No downloaded files to clean up")
    except Exception as e:
        print(f"❌ Error cleaning up files: {e}")

def execute_single_quiz_sync(user_id: int, file_name: str, timer_seconds: int) -> bool:
    """Execute a single quiz synchronously and wait for it to complete"""
    from SchedulerManager import get_bot_instance
    import json
    import threading
    import time
        
    bot = get_bot_instance()
    if not bot:
        print("❌ Bot instance not available")
        return False
    
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
    
    # Load quiz data
    try:
        file_path = os.path.join(os.getcwd(), file_name)
        if not os.path.exists(file_path):
            print(f"❌ Quiz file not found: {file_path}")
            return False
        
        with open(file_path, 'r', encoding='utf-8') as f:
            quiz_data = json.load(f)
        
    except Exception as e:
        print(f"❌ Error loading quiz file {file_name}: {e}")
        return False
    
    # Import the deliver_quiz_session function
    try:
        from SchedulerManager import send_message_with_retry, leaderboard_manager, HARDCODED_GROUP_ID
    except ImportError as e:
        print(f"❌ Could not import required functions: {e}")
        return False
    
    # Target chat ID (use hardcoded group)
    target_chat_id = HARDCODED_GROUP_ID
    leaderboard_chat_id = user_id
    
    # Run the quiz synchronously (not in a separate thread)
    quiz_completed = False
    quiz_success = False
    
    try:
        quiz_title = quiz_data.get('title', 'Quiz Session')
        questions = quiz_data.get('questions', [])
        
        if not questions:
            send_message_with_retry(bot_token, target_chat_id, "❌ No questions found in this quiz.")
            return False
        
        leaderboard_manager.start_quiz_session(leaderboard_chat_id, quiz_title, len(questions))
        
        start_message = f"🎯 {quiz_title}\n\n📊 Total Questions: {len(questions)}\n⏰ Timer: {timer_seconds} seconds per question\n🎮 Let's begin!"
        send_message_with_retry(bot_token, target_chat_id, start_message)
        
        # If quiz is posted in a group, notify the user in private chat
        if user_id != target_chat_id:
            try:
                private_notification = f"🎯 Your scheduled quiz '{quiz_title}' has started in the group!\n\n📊 Questions: {len(questions)}\n⏰ Timer: {timer_seconds}s per question"
                send_message_with_retry(bot_token, user_id, private_notification, max_retries=2)
            except Exception as e:
                print(f"⚠️ Could not send private notification to user {user_id}: {e}")
        
        time.sleep(2)
        
        # Process each question
        from SchedulerManager import deliver_single_question
        for i, question_data in enumerate(questions, 1):
            
            success = deliver_single_question(
                target_chat_id, question_data, i, len(questions), bot_token, timer_seconds, leaderboard_chat_id
            )
            
            if not success:
                print(f"❌ Failed to deliver question {i}")
                break
            
            time.sleep(1)
        
        # Generate and send leaderboard
        leaderboard_msg = leaderboard_manager.generate_leaderboard(leaderboard_chat_id)
        
        if leaderboard_msg:
            # Try to send leaderboard
            for attempt in range(3):
                try:
                    leaderboard_response = send_message_with_retry(bot_token, target_chat_id, leaderboard_msg, None)
                    if leaderboard_response:
                        break
                except Exception as e:
                    print(f"❌ Leaderboard send attempt {attempt + 1} error: {e}")
                
                if attempt < 2:
                    time.sleep(2)
        else:
            print("⚠️ No leaderboard data generated - sending completion message")
            send_message_with_retry(bot_token, target_chat_id, "🎉 Quiz completed! Thank you for participating.", None)
        
        # Finish session and upload user data
        upload_success = leaderboard_manager.finish_quiz_session(leaderboard_chat_id)
        if upload_success:
            pass
        
        quiz_success = True        
    except Exception as e:
        print(f"❌ Error during quiz execution: {e}")
        quiz_success = False
    
    finally:
        # Delete the quiz file after completion
        try:
            file_path = os.path.join(os.getcwd(), file_name)
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"❌ Error deleting quiz file {file_name}: {e}")
    
    return quiz_success

def execute_quiz_sequence(sequence_id: str):
    """Execute a quiz sequence"""
    def run_sequence():
        try:
            sequence = load_sequence(sequence_id)
            if not sequence:
                print(f"❌ Sequence not found: {sequence_id}")
                return
            
            active_sequences[sequence_id] = sequence
            
            sequence.status = "running"
            save_sequence(sequence)
            
            for i, quiz in enumerate(sequence.quizzes):
                sequence.current_quiz_index = i
                
                # Check if sequence is paused
                while sequence_id in paused_sequences:
                    time.sleep(5)
                
                quiz.status = "running"
                
                # Instead of using send_scheduled_notification_sync which returns immediately,
                # we need to run the quiz synchronously and wait for it to complete
                success = execute_single_quiz_sync(
                    sequence.user_id, 
                    quiz.file_name, 
                    quiz.timer_seconds
                )
                
                if success:
                    quiz.status = "completed"
                    
                    # If not the last quiz, handle gap time
                    if i < len(sequence.quizzes) - 1:
                        gap_seconds = quiz.gap_minutes * 60
                        
                    
                        # Wait for gap time minus 30 seconds
                        if gap_seconds > 30:
                            gap_wait_time = gap_seconds - 30
                            time.sleep(gap_wait_time)
                            
                            # Send 30-second warning
                            try:
                                bot = get_bot_instance()
                                if bot:
                                    from BrowseFile import bot as telegram_bot
                                    import asyncio
                                    
                                    next_quiz = sequence.quizzes[i + 1]
                                    warning_msg = f"⚠️ Next quiz starts in 30 seconds!\n\n🎯 Quiz {i+2}: {next_quiz.file_name}\n⏰ Timer: {next_quiz.timer_seconds}s per question"
                                    
                                    # Send to private chat
                                    try:
                                        asyncio.create_task(
                                            telegram_bot.send_message(
                                                chat_id=sequence.user_id,
                                                text=warning_msg
                                            )
                                        )
                                    except Exception as e:
                                        print(f"⚠️ Could not send 30s warning to private chat: {e}")
                            except Exception as e:
                                print(f"⚠️ Error sending 30s warning: {e}")
                            
                            # Wait remaining 30 seconds
                            time.sleep(30)
                        else:
                            # If gap is 30 seconds or less, just wait
                            time.sleep(gap_seconds)
                        
                    else:
                        pass
                else:
                    print(f"❌ Quiz {i+1} failed: {quiz.file_name}")
                    quiz.status = "failed"
            
            # Mark sequence as completed
            sequence.status = "completed"
            save_sequence(sequence)
            
            # Clean up downloaded files
            cleanup_quiz_files(sequence)
            
            # Remove from active sequences
            if sequence_id in active_sequences:
                del active_sequences[sequence_id]
                        
        except Exception as e:
            print(f"❌ Error executing sequence {sequence_id}: {e}")
            # Clean up files even if sequence failed
            try:
                cleanup_quiz_files(sequence)
            except:
                pass
            if sequence_id in active_sequences:
                del active_sequences[sequence_id]
    
    # Run sequence in background thread
    sequence_thread = threading.Thread(target=run_sequence)
    sequence_thread.daemon = True
    sequence_thread.start()

def pause_sequence(sequence_id: str) -> bool:
    """Pause a running sequence"""
    if sequence_id in active_sequences:
        paused_sequences.add(sequence_id)
        return True
    return False

def resume_sequence(sequence_id: str) -> bool:
    """Resume a paused sequence"""
    if sequence_id in paused_sequences:
        paused_sequences.remove(sequence_id)
        return True
    return False

def get_user_sequences(user_id: int) -> List[Dict]:
    """Get all sequences for a user"""
    try:
        init_sequence_database()
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, sequence_name, scheduled_time, status 
            FROM sequences 
            WHERE user_id = ? 
            ORDER BY scheduled_time DESC
        ''', (user_id,))
        
        results = cursor.fetchall()
        conn.close()
        
        sequences = []
        for row in results:
            sequences.append({
                'id': row[0],
                'name': row[1],
                'scheduled_time': row[2],
                'status': row[3]
            })
        
        return sequences
        
    except Exception as e:
        print(f"❌ Error getting user sequences: {e}")
        return []

# Initialize database on import
init_sequence_database()
