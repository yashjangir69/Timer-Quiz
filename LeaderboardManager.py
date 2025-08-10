"""
Leaderboard Manager for Quiz Bot
Handles user tracking, leaderboard generation, and Google Drive JSON management
"""

import json
import os
from typing import Dict, List, Optional, Tuple
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from Auth import authenticate
import tempfile

class LeaderboardManager:
    def __init__(self, users_file_id: str = None):
        """
        Initialize LeaderboardManager
        
        Args:
            users_file_id: Google Drive file ID for users.json
        """
        self.users_file_id = users_file_id or "103wefP2LJYCWCZsTPKM0ye1WFnI-Fk5o"
        self.users_file_name = "users.json"
        self.local_users_file = "users.json"
        self.quiz_sessions = {}  
        
    def download_users_file(self) -> bool:
        """Download users.json from Google Drive"""
        try:
            service = authenticate()
            request = service.files().get_media(fileId=self.users_file_id)
            
            with open(self.local_users_file, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    
            return True
            
        except Exception as e:
            print(f"⚠️ Error downloading users file: {e}")
            self._create_empty_users_file()
            return False
    
    def _create_empty_users_file(self):
        """Create empty users.json file if it doesn't exist"""
        try:
            empty_users = {"users": []}
            with open(self.local_users_file, 'w', encoding='utf-8') as f:
                json.dump(empty_users, f, indent=2, ensure_ascii=False)
            print("📝 Created empty users.json file")
        except Exception as e:
            print(f"❌ Error creating empty users file: {e}")
    
    def upload_users_file(self) -> bool:
        """Upload updated users.json back to Google Drive"""
        try:
            if not os.path.exists(self.local_users_file):
                print("❌ Local users file not found")
                return False
                
            service = authenticate()
            
            # Update the existing file
            media = MediaFileUpload(
                self.local_users_file, 
                mimetype='application/json',
                resumable=True
            )
            
            updated_file = service.files().update(
                fileId=self.users_file_id,
                media_body=media
            ).execute()
            
            return True
            
        except Exception as e:
            print(f"❌ Error uploading users file: {e}")
            return False
    
    def load_users(self) -> Dict:
        """Load users from local JSON file"""
        try:
            if not os.path.exists(self.local_users_file):
                self.download_users_file()
                
            with open(self.local_users_file, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
                
            return users_data
            
        except Exception as e:
            print(f"❌ Error loading users: {e}")
            return {"users": []}
    
    def save_users(self, users_data: Dict) -> bool:
        """Save users to local JSON file"""
        try:
            with open(self.local_users_file, 'w', encoding='utf-8') as f:
                json.dump(users_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"❌ Error saving users: {e}")
            return False
    
    def add_user_if_new(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> bool:
        """
        Add user to tracking if they don't already exist
        
        Args:
            user_id: Telegram user ID
            username: Telegram username (without @)
            first_name: User's first name
            last_name: User's last name
            
        Returns:
            True if user was added (new user), False if already exists
        """
        try:
            users_data = self.load_users()
            existing_user_ids = [user.get('user_id') for user in users_data.get('users', [])]
            
            if user_id in existing_user_ids:
                return False
            
            # Create user entry
            user_entry = {
                "user_id": user_id,
                "username": f"@{username}" if username else None,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": f"{first_name or ''} {last_name or ''}".strip(),
                "added_date": self._get_current_timestamp()
            }
            
            users_data['users'].append(user_entry)
            
            if self.save_users(users_data):
                return True
            else:
                return False
                
        except Exception as e:
            print(f"❌ Error adding user: {e}")
            return False
    
    def start_quiz_session(self, chat_id: int, quiz_title: str, total_questions: int):
        """Initialize a new quiz session for leaderboard tracking"""
        self.quiz_sessions[chat_id] = {
            "quiz_title": quiz_title,
            "total_questions": total_questions,
            "participants": {},  # user_id -> {name, correct_answers, total_answered}
            "current_question": 0,
            "start_time": self._get_current_timestamp()
        }
    
    def record_poll_answer(self, chat_id: int, user_id: int, username: str, first_name: str, 
                          last_name: str, is_correct: bool, question_number: int):
        """
        Record a user's poll answer for leaderboard
        
        Args:
            chat_id: Chat where quiz is happening
            user_id: User who answered
            username: User's username
            first_name: User's first name
            last_name: User's last name
            is_correct: Whether the answer was correct
            question_number: Current question number
        """
        try:
            if chat_id not in self.quiz_sessions:
                print(f"⚠️ No active quiz session for chat {chat_id}")
                return
            
            session = self.quiz_sessions[chat_id]
            
            # Add user to tracking (won't duplicate)
            self.add_user_if_new(user_id, username, first_name, last_name)
            
            # Initialize participant if first time answering
            if user_id not in session["participants"]:
                full_name = f"{first_name or ''} {last_name or ''}".strip()
                session["participants"][user_id] = {
                    "name": full_name or f"User {user_id}",
                    "username": f"@{username}" if username else None,
                    "correct_answers": 0,
                    "total_answered": 0
                }
            
            participant = session["participants"][user_id]
            participant["total_answered"] += 1
            if is_correct:
                participant["correct_answers"] += 1
                
            
        except Exception as e:
            print(f"❌ Error recording poll answer: {e}")
    
    def generate_leaderboard(self, chat_id: int) -> Optional[str]:
        """
        Generate leaderboard message for completed quiz
        
        Returns:
            Formatted leaderboard message or None if no data
        """
        try:
            if chat_id not in self.quiz_sessions:
                return None
                
            session = self.quiz_sessions[chat_id]
            participants = session["participants"]
            
            if not participants:
                return "📊 Quiz Leaderboard\n\nNo participants found for this quiz."
            
            # Sort participants by correct answers (descending), then by total answered
            sorted_participants = sorted(
                participants.items(),
                key=lambda x: (x[1]["correct_answers"], x[1]["total_answered"]),
                reverse=True
            )
            
            total_percentage = 0
            valid_participants = 0
            for user_id, data in participants.items():
                if data["total_answered"] > 0:
                    participant_percentage = (data["correct_answers"] / data["total_answered"]) * 100
                    total_percentage += participant_percentage
                    valid_participants += 1
            
            quiz_average = round(total_percentage / valid_participants) if valid_participants > 0 else 0
            
            # Build leaderboard message with simple formatting
            quiz_title = session['quiz_title']
            leaderboard_msg = f"🏆 {quiz_title} - Final Results\n\n"
            leaderboard_msg += f"👥 Total Participants: {len(participants)}\n"
            leaderboard_msg += f"📊 Total Average: {quiz_average}%\n\n"
            leaderboard_msg += "🎯 LEADERBOARD:\n"
            
            medals = ["🥇", "🥈", "🥉"]
            
            for i, (user_id, data) in enumerate(sorted_participants, 1):
                medal = medals[i-1] if i <= 3 else f"{i}."
                name = data["name"]
                username_display = f" ({data['username']})" if data.get("username") else ""
                
                score = data["correct_answers"]
                total = data["total_answered"]
                percentage = round((score/total)*100) if total > 0 else 0
                
                leaderboard_msg += f"{medal} {name}{username_display}\n"
                leaderboard_msg += f"    📊 {score}/{total} correct ({percentage}%)\n\n"
            
            leaderboard_msg += "🎉 Congratulations to all participants!"
            
            return leaderboard_msg
            
        except Exception as e:
            print(f"❌ Error generating leaderboard: {e}")
            # Return a simple fallback leaderboard
            try:
                if chat_id in self.quiz_sessions:
                    session = self.quiz_sessions[chat_id]
                    participants = session.get("participants", {})
                    if participants:
                        fallback_msg = f"📊 Quiz Results Summary\n\n"
                        fallback_msg += f"Quiz: {session.get('quiz_title', 'Quiz Session')}\n"
                        fallback_msg += f"Participants: {len(participants)}\n\n"
                        
                        for user_id, data in participants.items():
                            fallback_msg += f"• {data['name']}: {data['correct_answers']}/{data['total_answered']}\n"
                        
                        return fallback_msg
                    else:
                        return "📊 Quiz completed but no participant data available."
                else:
                    return "📊 Quiz session data not found."
            except:
                return "📊 Quiz completed! Leaderboard generation had an error but quiz data was processed."
    
    def finish_quiz_session(self, chat_id: int) -> bool:
        """
        Finish quiz session and upload updated users data to Google Drive
        
        Returns:
            True if successfully finished and uploaded
        """
        try:
            if chat_id in self.quiz_sessions:
                session_info = self.quiz_sessions[chat_id]
                
                # Upload updated users file to Google Drive
                upload_success = self.upload_users_file()
                
                # Clean up session data
                del self.quiz_sessions[chat_id]
                
                return upload_success
            else:
                print(f"⚠️ No active session found for chat {chat_id}")
                return False
                
        except Exception as e:
            print(f"❌ Error finishing quiz session: {e}")
            return False
    
    def _escape_markdown(self, text: str) -> str:
        """Escape special characters for MarkdownV2"""
        if not text:
            return ""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp as ISO string"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_quiz_stats(self, chat_id: int) -> Dict:
        """Get current quiz session statistics"""
        if chat_id not in self.quiz_sessions:
            return {}
        return self.quiz_sessions[chat_id]
    
    def cleanup_old_sessions(self):
        """Clean up old quiz sessions (can be called periodically)"""
        try:
            current_time = self._get_current_timestamp()
        except Exception as e:
            print(f"❌ Error during cleanup: {e}")

leaderboard_manager = LeaderboardManager()
