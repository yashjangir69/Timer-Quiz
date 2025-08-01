"""
Flask App for keeping the Telegram Bot alive on Render
"""

import os
import threading
import asyncio
import logging
from flask import Flask, jsonify
from main_new import TelegramQuizBot

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot instance
bot_instance = None
bot_thread = None

def run_bot():
    """Run the bot in a separate thread"""
    global bot_instance
    try:
        # Configuration - Replace with your actual values
        BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
        GROUP_ID = int(os.getenv("GROUP_ID", "-1001234567890"))
        
        bot_instance = TelegramQuizBot(BOT_TOKEN, GROUP_ID)
        
        # Run the bot
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot_instance.run())
        
    except Exception as e:
        logger.error(f"Error running bot: {e}")

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        "status": "alive",
        "message": "Telegram Quiz Bot is running",
        "bot_active": bot_instance is not None
    })

@app.route('/health')
def health():
    """Health check for UptimeRobot"""
    return jsonify({
        "status": "healthy",
        "uptime": "running"
    })

@app.route('/status')
def status():
    """Bot status endpoint"""
    if bot_instance:
        return jsonify({
            "bot_status": "running",
            "scheduler_running": bot_instance.scheduler.running if bot_instance.scheduler else False,
            "active_sessions": len(bot_instance.user_sessions)
        })
    else:
        return jsonify({
            "bot_status": "not running"
        })

if __name__ == '__main__':
    import os
    
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Started bot thread")
    
    # Start Flask app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
