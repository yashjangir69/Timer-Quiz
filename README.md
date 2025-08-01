# Telegram Quiz Bot

A production-level Telegram bot that manages quizzes from Google Drive with complete folder navigation, scheduling, and leaderboards.

## Features

🎯 **Complete Quiz Management System**
- Browse Google Drive folders with deep nesting support
- Select quiz files from any folder depth
- Configure quiz settings (shuffle, timing, scheduling)
- Automatic quiz posting to Telegram groups
- Real-time leaderboards after quiz completion

📚 **Folder Navigation**
- Preserves exact Google Drive folder structure
- Support for unlimited folder depth
- Breadcrumb navigation
- File filtering (only .json quiz files)

⚙️ **Quiz Configuration**
- Shuffle questions option
- Custom timer per question (5-300 seconds)
- Flexible scheduling (time input parsing)
- Confirmation before scheduling

🎮 **Group Quiz Features**
- Quiz title display before starting
- Question + options as text message
- Native Telegram quiz polls
- Automatic explanation reveal after timer
- Comprehensive leaderboard with rankings

👥 **User Tracking**
- Automatic user discovery from poll participation
- Minimal user data storage (ID, username, first seen date)
- Google Drive integration for user data persistence

## Setup Instructions

### 1. Prerequisites
- Python 3.8+
- Google Drive API credentials
- Telegram Bot Token
- Telegram Group ID

### 2. Google Drive Setup
1. Create a Google Cloud Project
2. Enable Google Drive API
3. Create service account credentials
4. Download `credentials.json`
5. Create `token.pickle` by running authentication
6. Create a "Quizzes" folder in your Google Drive
7. Organize your quiz files in nested folders

### 3. Installation

```bash
# Clone or download the project
cd quiz-bot

# Install dependencies
pip install -r requirements.txt

# Create environment file
cp .env.example .env

# Edit .env with your values
BOT_TOKEN=your_telegram_bot_token
GROUP_ID=-1001234567890
```

### 4. Quiz File Format

Create JSON files in your Google Drive "Quizzes" folder:

```json
{
  "title": "Sample Quiz Title",
  "questions": [
    {
      "question": "What is the capital of India?",
      "options": [
        "Mumbai",
        "Delhi", 
        "Kolkata",
        "Chennai"
      ],
      "correct": 1,
      "explanation": "Delhi is the capital of India."
    }
  ]
}
```

### 5. Local Development

```bash
# Run the bot locally
python main_new.py
```

### 6. Production Deployment (Render)

1. **Prepare for Render:**
   - Ensure all files are in your repository
   - Add your `credentials.json` and `token.pickle` files
   - Set environment variables in Render dashboard

2. **Deploy to Render:**
   - Connect your GitHub repository
   - Set build command: `pip install -r requirements.txt`
   - Set start command: `python app.py`
   - Add environment variables: `BOT_TOKEN`, `GROUP_ID`, `PORT`

3. **UptimeRobot Setup:**
   - Add your Render app URL to UptimeRobot
   - Set ping interval to keep the app alive
   - Monitor endpoint: `https://your-app.render.com/health`

## File Structure

```
quiz-bot/
├── main_new.py          # Main bot application
├── app.py               # Flask wrapper for Render
├── drive_utils.py       # Google Drive operations
├── quiz_manager.py      # Quiz execution logic
├── user_tracker.py      # User tracking functionality
├── config.py            # Configuration management
├── requirements.txt     # Python dependencies
├── Procfile            # Render deployment config
├── .env.example        # Environment variables template
├── credentials.json    # Google Drive credentials (your file)
├── token.pickle        # Google Drive token (generated)
└── README.md           # This file
```

## Usage

### For Bot Users (Private Chat):
1. Send `/start` to the bot
2. Navigate through folders using inline buttons
3. Select a quiz file
4. Configure settings:
   - Choose shuffle option
   - Enter schedule time (e.g., "3:45 PM")
   - Set timer duration (e.g., "30" for 30 seconds)
5. Confirm configuration
6. Quiz will automatically post to the group at scheduled time

### Quiz Flow in Group:
1. Quiz title and info displayed
2. For each question:
   - Text message with question and options (A, B, C, D)
   - Telegram quiz poll with correct answer
   - After timer expires, explanation is added to question message
3. Final leaderboard with participant scores

## Configuration Options

### Timer Settings:
- Minimum: 5 seconds per question
- Maximum: 300 seconds per question
- Default: 30 seconds per question

### Scheduling:
- Supports various time formats: "3:45 PM", "15:30", "9:00 AM"
- Automatically schedules for next day if time has passed
- Persistent scheduling survives bot restarts

### User Data:
- Only tracks users who participate in polls
- Stores: user ID, username, first seen date
- Data saved to `users.json` on Google Drive
- New users only (doesn't duplicate existing entries)

## Troubleshooting

### Common Issues:

1. **"Quizzes folder not found"**
   - Ensure you have a folder named "Quizzes" in your Google Drive
   - Check Google Drive API permissions

2. **"Session expired"**
   - User took too long to complete configuration
   - Send `/start` again to restart

3. **Quiz not posting at scheduled time**
   - Check bot logs for scheduler errors
   - Verify group ID is correct
   - Ensure bot has posting permissions in group

4. **Flask/Render issues**
   - Check environment variables are set correctly
   - Verify all dependencies are installed
   - Monitor Render logs for errors

### Logs:
- Bot activities logged to `bot.log`
- Use log levels: INFO, ERROR, DEBUG
- Monitor for Google Drive API limits

## Support

For issues and questions:
1. Check the logs first (`bot.log`)
2. Verify Google Drive and Telegram permissions
3. Test with a simple quiz file
4. Check network connectivity for API calls

## Security Notes

- Keep `credentials.json` and `token.pickle` secure
- Use environment variables for sensitive data
- Regularly monitor bot usage and API quotas
- Restrict bot permissions to necessary channels only
