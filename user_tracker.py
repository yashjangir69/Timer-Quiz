"""
User Tracker - Handles user tracking and updates users.json on Google Drive
"""

import logging
from datetime import datetime
from typing import Dict, Any, Set
from telegram import User

logger = logging.getLogger(__name__)

class UserTracker:
    def __init__(self, drive_handler):
        self.drive_handler = drive_handler
        self.new_users = {}  # Store new users during quiz session

    def track_poll_participants(self, poll_answers: Dict[int, Any]) -> Dict[str, Dict[str, str]]:
        """Track users who participated in polls"""
        new_users_data = {}
        
        for user_id, user_info in poll_answers.items():
            user_id_str = str(user_id)
            
            # Only track new users (check if already exists will be done in drive_handler)
            if user_id_str not in self.new_users:
                try:
                    # Extract user information
                    username = user_info.get('username', '')
                    first_name = user_info.get('first_name', '')
                    
                    # Create user data
                    user_data = {
                        'username': username or first_name,
                        'first_seen': datetime.now().strftime('%Y-%m-%d')
                    }
                    
                    new_users_data[user_id_str] = user_data
                    self.new_users[user_id_str] = user_data
                    
                    logger.info(f"Tracked new user: {user_id} - {username or first_name}")
                    
                except Exception as e:
                    logger.error(f"Error tracking user {user_id}: {e}")
        
        return new_users_data

    def extract_user_info_from_poll_answer(self, user: User) -> Dict[str, str]:
        """Extract user information from Telegram User object"""
        return {
            'username': user.username or '',
            'first_name': user.first_name or '',
            'last_name': user.last_name or ''
        }

    async def update_users_on_drive(self):
        """Update users.json file on Google Drive with new users"""
        if not self.new_users:
            logger.info("No new users to update")
            return
        
        try:
            self.drive_handler.update_users_file(self.new_users)
            logger.info(f"Updated {len(self.new_users)} new users on Google Drive")
            
            # Clear new users after successful update
            self.new_users.clear()
            
        except Exception as e:
            logger.error(f"Error updating users on Google Drive: {e}")

    def add_user_from_poll_answer(self, user_id: int, user: User):
        """Add user from poll answer"""
        user_id_str = str(user_id)
        
        if user_id_str not in self.new_users:
            user_data = {
                'username': user.username or user.first_name or f"user_{user_id}",
                'first_seen': datetime.now().strftime('%Y-%m-%d')
            }
            
            self.new_users[user_id_str] = user_data
            logger.info(f"Added new user from poll: {user_id} - {user_data['username']}")

    def get_new_users_count(self) -> int:
        """Get count of new users tracked in current session"""
        return len(self.new_users)

    def clear_session_data(self):
        """Clear session data (called after drive update)"""
        self.new_users.clear()
