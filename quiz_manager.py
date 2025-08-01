"""
Quiz Manager - Handles quiz operations, scheduling and execution
"""

import json
import logging
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from telegram import Bot
from telegram.constants import PollType

logger = logging.getLogger(__name__)

class QuizManager:
    def __init__(self):
        self.active_quizzes = {}  # quiz_id -> quiz_data
        self.question_messages = {}  # quiz_id -> {question_num -> message_id}
        self.user_scores = {}  # quiz_id -> {user_id -> score}
        self.quiz_participants = {}  # quiz_id -> set of user_ids

    def prepare_quiz(self, quiz_data: Dict[str, Any], shuffle: bool = False) -> str:
        """Prepare quiz for execution and return quiz ID"""
        quiz_id = f"quiz_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Copy quiz data
        prepared_quiz = quiz_data.copy()
        
        # Shuffle questions if requested
        if shuffle:
            random.shuffle(prepared_quiz['questions'])
        
        # Add metadata
        prepared_quiz['quiz_id'] = quiz_id
        prepared_quiz['created_at'] = datetime.now().isoformat()
        prepared_quiz['shuffled'] = shuffle
        
        # Store in active quizzes
        self.active_quizzes[quiz_id] = prepared_quiz
        self.question_messages[quiz_id] = {}
        self.user_scores[quiz_id] = {}
        self.quiz_participants[quiz_id] = set()
        
        logger.info(f"Prepared quiz {quiz_id} with {len(prepared_quiz['questions'])} questions")
        return quiz_id

    async def execute_quiz(self, bot: Bot, group_id: int, quiz_id: str, timer_per_question: int):
        """Execute the entire quiz in the group"""
        if quiz_id not in self.active_quizzes:
            logger.error(f"Quiz {quiz_id} not found in active quizzes")
            return

        quiz_data = self.active_quizzes[quiz_id]
        questions = quiz_data['questions']
        
        try:
            # Send quiz title
            title_message = f"🎯 **{quiz_data['title']}**\n\n📝 Total Questions: {len(questions)}\n⏱️ Time per question: {timer_per_question}s\n\nLet's begin! 🚀"
            await bot.send_message(chat_id=group_id, text=title_message, parse_mode='Markdown')
            
            # Execute each question
            for i, question_data in enumerate(questions, 1):
                await self._execute_question(
                    bot, group_id, quiz_id, i, question_data, timer_per_question
                )
                
                # Wait between questions (small buffer)
                if i < len(questions):
                    await asyncio.sleep(2)
            
            # Show final leaderboard
            await self._show_final_leaderboard(bot, group_id, quiz_id)
            
        except Exception as e:
            logger.error(f"Error executing quiz {quiz_id}: {e}")
        finally:
            # Cleanup
            await self._cleanup_quiz(quiz_id)

    async def _execute_question(self, bot: Bot, group_id: int, quiz_id: str, 
                              question_num: int, question_data: Dict[str, Any], 
                              timer: int):
        """Execute a single question"""
        try:
            # Format question text
            question_text = self._format_question_text(question_num, question_data)
            
            # Send question message
            question_msg = await bot.send_message(
                chat_id=group_id, 
                text=question_text, 
                parse_mode='Markdown'
            )
            
            # Store message ID for later editing
            self.question_messages[quiz_id][question_num] = question_msg.message_id
            
            # Send poll immediately after
            poll_msg = await bot.send_poll(
                chat_id=group_id,
                question=f"Q{question_num}. Choose your answer:",
                options=['A', 'B', 'C', 'D'],
                type=PollType.QUIZ,
                correct_option_id=question_data['correct'],
                is_anonymous=False,
                allows_multiple_answers=False
            )
            
            # Wait for the timer
            await asyncio.sleep(timer)
            
            # Edit question message to add explanation
            explanation_text = self._format_question_with_explanation(question_num, question_data)
            await bot.edit_message_text(
                chat_id=group_id,
                message_id=question_msg.message_id,
                text=explanation_text,
                parse_mode='Markdown'
            )
            
            logger.info(f"Completed question {question_num} for quiz {quiz_id}")
            
        except Exception as e:
            logger.error(f"Error executing question {question_num}: {e}")

    def _format_question_text(self, question_num: int, question_data: Dict[str, Any]) -> str:
        """Format question text for initial display"""
        text = f"**Q{question_num}.** {question_data['question']}\n\n"
        
        for i, option in enumerate(question_data['options']):
            letter = chr(65 + i)  # A, B, C, D
            text += f"**{letter}.** {option}\n"
        
        return text

    def _format_question_with_explanation(self, question_num: int, question_data: Dict[str, Any]) -> str:
        """Format question text with explanation"""
        text = f"**Q{question_num}.** {question_data['question']}\n\n"
        
        for i, option in enumerate(question_data['options']):
            letter = chr(65 + i)  # A, B, C, D
            if i == question_data['correct']:
                text += f"**{letter}.** {option} ✅\n"
            else:
                text += f"**{letter}.** {option}\n"
        
        text += f"\n💡 **Explanation:** {question_data['explanation']}"
        return text

    async def _show_final_leaderboard(self, bot: Bot, group_id: int, quiz_id: str):
        """Show final leaderboard after quiz completion"""
        try:
            if quiz_id not in self.user_scores:
                await bot.send_message(
                    chat_id=group_id,
                    text="🏁 Quiz Finished\n👤 Participants: 0\n\nNo participants found."
                )
                return

            scores = self.user_scores[quiz_id]
            total_questions = len(self.active_quizzes[quiz_id]['questions'])
            
            if not scores:
                await bot.send_message(
                    chat_id=group_id,
                    text="🏁 Quiz Finished\n👤 Participants: 0\n\nNo participants found."
                )
                return
            
            # Sort users by score (descending)
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            
            # Format leaderboard
            leaderboard_text = f"🏁 Quiz Finished\n👤 Participants: {len(sorted_scores)}\n\n"
            
            medals = ["🥇", "🥈", "🥉"]
            
            for i, (user_id, score) in enumerate(sorted_scores[:10]):  # Top 10
                try:
                    user = await bot.get_chat_member(group_id, user_id)
                    username = user.user.username or user.user.first_name
                    username = f"@{username}" if user.user.username else username
                except:
                    username = f"User {user_id}"
                
                medal = medals[i] if i < 3 else f"{i+1}."
                leaderboard_text += f"{medal} {username} — {score}/{total_questions}\n"
            
            await bot.send_message(
                chat_id=group_id,
                text=leaderboard_text,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error showing leaderboard: {e}")

    def handle_poll_answer(self, quiz_id: str, user_id: int, question_num: int, 
                          selected_option: int, correct_option: int) -> bool:
        """Handle poll answer and update scores"""
        if quiz_id not in self.user_scores:
            self.user_scores[quiz_id] = {}
        
        if user_id not in self.user_scores[quiz_id]:
            self.user_scores[quiz_id][user_id] = 0
        
        # Add user to participants
        if quiz_id in self.quiz_participants:
            self.quiz_participants[quiz_id].add(user_id)
        
        # Check if answer is correct
        is_correct = selected_option == correct_option
        if is_correct:
            self.user_scores[quiz_id][user_id] += 1
        
        return is_correct

    async def _cleanup_quiz(self, quiz_id: str):
        """Clean up quiz data after completion"""
        try:
            # Remove from active quizzes
            if quiz_id in self.active_quizzes:
                del self.active_quizzes[quiz_id]
            
            if quiz_id in self.question_messages:
                del self.question_messages[quiz_id]
            
            # Keep scores temporarily for leaderboard, but clean up later
            # self.user_scores and quiz_participants will be cleaned by garbage collection
            
            logger.info(f"Cleaned up quiz {quiz_id}")
            
        except Exception as e:
            logger.error(f"Error cleaning up quiz {quiz_id}: {e}")

    def get_quiz_info(self, quiz_id: str) -> Optional[Dict[str, Any]]:
        """Get quiz information"""
        return self.active_quizzes.get(quiz_id)

    def get_participant_count(self, quiz_id: str) -> int:
        """Get number of participants for a quiz"""
        return len(self.quiz_participants.get(quiz_id, set()))

    def get_user_scores_for_tracking(self, quiz_id: str) -> Dict[int, int]:
        """Get user scores for user tracking purposes"""
        return self.user_scores.get(quiz_id, {})
