"""
MessageUtils.py - Utility functions for sending messages via the Telegram bot
This file demonstrates how to send messages from anywhere in your project
"""

import asyncio
from BrowseFile import send_bot_message, send_quiz_notification, get_bot

async def send_welcome_message(chat_id: int, username: str = None):
    """Send a welcome message to a user"""
    name = username if username else "there"
    message = f"👋 Hello {name}!\n\n"
    message += "🎯 Welcome to the Quiz Scheduler Bot!\n"
    message += "📚 You can schedule quiz files and get notified when they're ready.\n\n"
    message += "Use /start to begin browsing files."
    
    return await send_bot_message(chat_id, message, parse_mode="Markdown")

async def send_error_message(chat_id: int, error: str):
    """Send an error message to a user"""
    message = f"❌ **Error occurred:**\n\n`{error}`\n\n"
    message += "Please try again or contact support if the issue persists."
    
    return await send_bot_message(chat_id, message, parse_mode="Markdown")

async def send_success_message(chat_id: int, action: str):
    """Send a success message to a user"""
    message = f"✅ **Success!**\n\n{action}"
    
    return await send_bot_message(chat_id, message, parse_mode="Markdown")

async def send_custom_notification(chat_id: int, title: str, content: str):
    """Send a custom notification"""
    message = f"🔔 **{title}**\n\n{content}"
    
    return await send_bot_message(chat_id, message, parse_mode="Markdown")

# Example usage function
async def example_usage():
    """Example of how to use the messaging functions"""
    chat_id = 123456789  # Replace with actual chat ID
    
    # Send different types of messages
    await send_welcome_message(chat_id, "John")
    await send_success_message(chat_id, "File has been successfully processed!")
    await send_error_message(chat_id, "File not found")
    await send_custom_notification(chat_id, "Reminder", "Your quiz starts in 5 minutes!")
    
    # Send quiz notification
    quiz_data = {
        "title": "Python Basics Quiz",
        "questions": [{"q": "What is Python?"}, {"q": "What is a variable?"}]
    }
    await send_quiz_notification(chat_id, quiz_data)

if __name__ == "__main__":
    # Example of running message functions independently
    asyncio.run(example_usage())
