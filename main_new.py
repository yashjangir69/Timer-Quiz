"""
Telegram Quiz Bot - Main File
Production-level bot for managing quizzes from Google Drive
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, PollAnswerHandler
)
from telegram.constants import PollType
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from dateutil import parser
import pytz

from drive_utils import DriveHandler
from quiz_manager import QuizManager
from user_tracker import UserTracker

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TelegramQuizBot:
    def __init__(self, bot_token: str, group_id: int):
        self.bot_token = bot_token
        self.group_id = group_id
        self.drive_handler = DriveHandler()
        self.quiz_manager = QuizManager()
        self.user_tracker = UserTracker(self.drive_handler)
        
        # Initialize scheduler
        jobstores = {'default': MemoryJobStore()}
        self.scheduler = AsyncIOScheduler(jobstores=jobstores)
        self.scheduler.start()
        
        # Store user sessions
        self.user_sessions = {}  # user_id -> session_data
        self.current_polls = {}  # poll_id -> quiz_info
        
        logger.info("TelegramQuizBot initialized successfully")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - show main quiz folders"""
        user_id = update.effective_user.id
        
        # Only work in private chat
        if update.effective_chat.type != 'private':
            return
        
        try:
            # Get main folders from Google Drive
            folders = self.drive_handler.get_folder_contents()
            
            if not folders:
                await update.message.reply_text("❌ No quiz folders found in Google Drive.")
                return
            
            # Create inline keyboard with folders
            keyboard = []
            for item in folders:
                if item['type'] == 'folder':
                    callback_data = f"folder_{item['id']}"
                    keyboard.append([InlineKeyboardButton(
                        f"📁 {item['name']}", 
                        callback_data=callback_data
                    )])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            welcome_text = (
                "🎯 **Welcome to Quiz Bot!**\n\n"
                "📚 Choose a quiz category to explore:\n\n"
                "📁 Navigate through folders to find quizzes\n"
                "⚙️ Configure quiz settings before scheduling\n"
                "🎮 Quizzes will be posted in the group automatically"
            )
            
            await update.message.reply_text(
                welcome_text, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text("❌ Error loading quiz folders. Please try again.")

    async def handle_folder_navigation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle folder navigation callback"""
        query = update.callback_query
        await query.answer()
        
        try:
            callback_data = query.data
            
            if callback_data.startswith("folder_"):
                folder_id = callback_data.replace("folder_", "")
                await self._show_folder_contents(query, folder_id)
            
            elif callback_data.startswith("back_"):
                parent_folder_id = callback_data.replace("back_", "")
                await self._show_folder_contents(query, parent_folder_id)
            
            elif callback_data.startswith("quiz_"):
                file_id = callback_data.replace("quiz_", "")
                await self._start_quiz_configuration(query, file_id)
            
            elif callback_data.startswith("shuffle_"):
                await self._handle_shuffle_choice(query, callback_data)
            
            elif callback_data.startswith("confirm_"):
                await self._handle_quiz_confirmation(query, callback_data)
                
        except Exception as e:
            logger.error(f"Error in folder navigation: {e}")
            await query.edit_message_text("❌ Error processing request. Please try again.")

    async def _show_folder_contents(self, query, folder_id: str):
        """Show contents of a specific folder"""
        try:
            contents = self.drive_handler.get_folder_contents(folder_id)
            
            if not contents:
                await query.edit_message_text("📁 This folder is empty.")
                return
            
            # Get breadcrumb path
            path = self.drive_handler.get_breadcrumb_path(folder_id)
            
            keyboard = []
            
            # Add folders first
            for item in contents:
                if item['type'] == 'folder':
                    callback_data = f"folder_{item['id']}"
                    keyboard.append([InlineKeyboardButton(
                        f"📁 {item['name']}", 
                        callback_data=callback_data
                    )])
            
            # Add quiz files
            for item in contents:
                if item['type'] == 'file' and item['is_quiz']:
                    callback_data = f"quiz_{item['id']}"
                    quiz_name = item['name'].replace('.json', '')
                    keyboard.append([InlineKeyboardButton(
                        f"🎯 {quiz_name}", 
                        callback_data=callback_data
                    )])
            
            # Add back button (if not in root)
            if folder_id != self.drive_handler.quizzes_folder_id:
                keyboard.append([InlineKeyboardButton(
                    "⬅️ Back", 
                    callback_data=f"back_{self.drive_handler.quizzes_folder_id}"
                )])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_text = f"📍 **Current Location:** {path}\n\n📂 Choose a folder or quiz:"
            
            await query.edit_message_text(
                message_text, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing folder contents: {e}")
            await query.edit_message_text("❌ Error loading folder contents.")

    async def _start_quiz_configuration(self, query, file_id: str):
        """Start quiz configuration process"""
        user_id = query.from_user.id
        
        try:
            # Download quiz file to get metadata
            quiz_data = self.drive_handler.download_quiz_file(file_id, f"preview_{file_id}.json")
            
            if not quiz_data:
                await query.edit_message_text("❌ Error loading quiz file.")
                return
            
            # Store quiz info in user session
            self.user_sessions[user_id] = {
                'file_id': file_id,
                'quiz_data': quiz_data,
                'step': 'shuffle'
            }
            
            # Show quiz info and shuffle option
            quiz_info = (
                f"🎯 **Quiz Selected:** {quiz_data['title']}\n"
                f"📝 **Questions:** {len(quiz_data['questions'])}\n\n"
                "🔀 **Do you want to shuffle the questions?**"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, Shuffle", callback_data=f"shuffle_yes_{user_id}"),
                    InlineKeyboardButton("❌ No, Keep Order", callback_data=f"shuffle_no_{user_id}")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                quiz_info, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error starting quiz configuration: {e}")
            await query.edit_message_text("❌ Error configuring quiz.")

    async def _handle_shuffle_choice(self, query, callback_data: str):
        """Handle shuffle choice"""
        user_id = query.from_user.id
        
        if user_id not in self.user_sessions:
            await query.edit_message_text("❌ Session expired. Please start again with /start")
            return
        
        try:
            shuffle_choice = "yes" in callback_data
            self.user_sessions[user_id]['shuffle'] = shuffle_choice
            self.user_sessions[user_id]['step'] = 'schedule_time'
            
            instruction_text = (
                f"🎯 **Quiz:** {self.user_sessions[user_id]['quiz_data']['title']}\n"
                f"🔀 **Shuffle:** {'Yes' if shuffle_choice else 'No'}\n\n"
                "⏰ **Please enter the schedule time**\n"
                "Format: HH:MM AM/PM (e.g., 3:45 PM)\n\n"
                "Send your message with the time:"
            )
            
            await query.edit_message_text(instruction_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling shuffle choice: {e}")
            await query.edit_message_text("❌ Error processing choice.")

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages for configuration input"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions:
            return
        
        session = self.user_sessions[user_id]
        
        try:
            if session['step'] == 'schedule_time':
                await self._handle_schedule_time_input(update, session)
            elif session['step'] == 'timer_duration':
                await self._handle_timer_input(update, session)
                
        except Exception as e:
            logger.error(f"Error handling text message: {e}")
            await update.message.reply_text("❌ Error processing input. Please try again.")

    async def _handle_schedule_time_input(self, update: Update, session: Dict):
        """Handle schedule time input"""
        time_text = update.message.text.strip()
        user_id = update.effective_user.id
        
        try:
            # Parse time input
            today = datetime.now().date()
            time_str = f"{today} {time_text}"
            
            parsed_time = parser.parse(time_str, fuzzy=True)
            
            # If time is in the past, schedule for tomorrow
            if parsed_time < datetime.now():
                parsed_time += timedelta(days=1)
            
            session['schedule_time'] = parsed_time
            session['step'] = 'timer_duration'
            
            response_text = (
                f"✅ **Scheduled Time:** {parsed_time.strftime('%Y-%m-%d %I:%M %p')}\n\n"
                "⏱️ **Enter timer duration per question (in seconds)**\n"
                "Example: 30 (for 30 seconds per question)\n\n"
                "Send your message with the duration:"
            )
            
            await update.message.reply_text(response_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error parsing time: {e}")
            await update.message.reply_text(
                "❌ Invalid time format. Please use format like:\n"
                "• 3:45 PM\n"
                "• 15:30\n"
                "• 9:00 AM"
            )

    async def _handle_timer_input(self, update: Update, session: Dict):
        """Handle timer duration input"""
        timer_text = update.message.text.strip()
        user_id = update.effective_user.id
        
        try:
            timer_duration = int(timer_text)
            
            if timer_duration < 5 or timer_duration > 300:
                await update.message.reply_text(
                    "❌ Timer must be between 5 and 300 seconds."
                )
                return
            
            session['timer_duration'] = timer_duration
            session['step'] = 'confirmation'
            
            # Show confirmation
            quiz_data = session['quiz_data']
            schedule_time = session['schedule_time']
            
            confirmation_text = (
                "📋 **Quiz Configuration Summary**\n\n"
                f"🎯 **Quiz:** {quiz_data['title']}\n"
                f"📝 **Questions:** {len(quiz_data['questions'])}\n"
                f"🔀 **Shuffle:** {'Yes' if session['shuffle'] else 'No'}\n"
                f"⏰ **Schedule:** {schedule_time.strftime('%Y-%m-%d %I:%M %p')}\n"
                f"⏱️ **Timer per Question:** {timer_duration} seconds\n\n"
                "✅ **Confirm and schedule this quiz?**"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Confirm & Schedule", callback_data=f"confirm_yes_{user_id}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"confirm_no_{user_id}")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                confirmation_text, 
                reply_markup=reply_markup, 
                parse_mode='Markdown'
            )
            
        except ValueError:
            await update.message.reply_text(
                "❌ Please enter a valid number for timer duration."
            )
        except Exception as e:
            logger.error(f"Error handling timer input: {e}")
            await update.message.reply_text("❌ Error processing timer input.")

    async def _handle_quiz_confirmation(self, query, callback_data: str):
        """Handle quiz confirmation"""
        user_id = query.from_user.id
        
        if user_id not in self.user_sessions:
            await query.edit_message_text("❌ Session expired. Please start again with /start")
            return
        
        try:
            if "confirm_yes" in callback_data:
                session = self.user_sessions[user_id]
                
                # Download full quiz data
                quiz_data = self.drive_handler.download_quiz_file(
                    session['file_id'], 
                    f"quiz_{user_id}_{int(datetime.now().timestamp())}.json"
                )
                
                if not quiz_data:
                    await query.edit_message_text("❌ Error downloading quiz file.")
                    return
                
                # Prepare quiz
                quiz_id = self.quiz_manager.prepare_quiz(quiz_data, session['shuffle'])
                
                # Schedule quiz
                self.scheduler.add_job(
                    self._execute_scheduled_quiz,
                    'date',
                    run_date=session['schedule_time'],
                    args=[quiz_id, session['timer_duration']],
                    id=f"quiz_{quiz_id}",
                    replace_existing=True
                )
                
                success_text = (
                    "✅ **Quiz Scheduled Successfully!**\n\n"
                    f"🎯 **Quiz:** {quiz_data['title']}\n"
                    f"⏰ **Time:** {session['schedule_time'].strftime('%Y-%m-%d %I:%M %p')}\n"
                    f"🎮 **Group:** Quiz will be posted automatically\n\n"
                    "🔔 The quiz will start at the scheduled time!"
                )
                
                await query.edit_message_text(success_text, parse_mode='Markdown')
                
                # Clean up session
                del self.user_sessions[user_id]
                
            else:
                await query.edit_message_text("❌ Quiz scheduling cancelled.")
                del self.user_sessions[user_id]
                
        except Exception as e:
            logger.error(f"Error handling confirmation: {e}")
            await query.edit_message_text("❌ Error scheduling quiz.")

    async def _execute_scheduled_quiz(self, quiz_id: str, timer_duration: int):
        """Execute scheduled quiz"""
        try:
            from telegram import Bot
            bot = Bot(token=self.bot_token)
            
            logger.info(f"Starting scheduled quiz {quiz_id}")
            
            # Execute quiz
            await self.quiz_manager.execute_quiz(bot, self.group_id, quiz_id, timer_duration)
            
            # Update user tracking
            await self.user_tracker.update_users_on_drive()
            
            # Clean up temporary files
            self.drive_handler.cleanup_temp_files()
            
            logger.info(f"Completed scheduled quiz {quiz_id}")
            
        except Exception as e:
            logger.error(f"Error executing scheduled quiz {quiz_id}: {e}")

    async def handle_poll_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle poll answers for scoring"""
        try:
            poll_answer = update.poll_answer
            user = poll_answer.user
            
            # Track user for users.json update
            self.user_tracker.add_user_from_poll_answer(user.id, user)
            
            logger.info(f"Poll answer received from user {user.id}")
            
        except Exception as e:
            logger.error(f"Error handling poll answer: {e}")

    def setup_handlers(self, app):
        """Setup all handlers for the bot"""
        # Command handlers
        app.add_handler(CommandHandler("start", self.start_command))
        
        # Callback query handler for inline buttons
        app.add_handler(CallbackQueryHandler(self.handle_folder_navigation))
        
        # Text message handler for configuration input
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, 
            self.handle_text_message
        ))
        
        # Poll answer handler
        app.add_handler(PollAnswerHandler(self.handle_poll_answer))

    async def run(self):
        """Run the bot"""
        app = None
        try:
            # Create application
            app = Application.builder().token(self.bot_token).build()
            
            # Setup handlers
            self.setup_handlers(app)
            
            # Initialize bot
            await app.initialize()
            
            logger.info("Bot started successfully")
            
            # Start polling
            await app.run_polling()
            
        except Exception as e:
            logger.error(f"Error running bot: {e}")
            if app and app.is_initialized():
                try:
                    await app.stop()
                except Exception:
                    pass
                try:
                    await app.shutdown()
                except Exception:
                    pass
        finally:
            # Cleanup scheduler
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown(wait=False)

if __name__ == "__main__":
    # Configuration
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your bot token
    GROUP_ID = -1001234567890  # Replace with your group ID
    
    # Create and run bot
    bot = TelegramQuizBot(BOT_TOKEN, GROUP_ID)
    asyncio.run(bot.run())
