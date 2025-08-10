# 🎯 Production-Grade Quiz Bot with Leaderboard System

## 🚀 Overview
This is a comprehensive Telegram quiz bot with advanced features including:
- **Dynamic Timer System**: Custom poll duration (5-300 seconds) per quiz
- **Production-Grade Error Handling**: Telegram server timeout management
- **Leaderboard System**: Real-time participant tracking with Google Drive integration
- **User Data Management**: Automatic user tracking without duplicates
- **Retry Mechanisms**: Exponential backoff for network issues

## 📁 File Structure
```
├── BrowseFile.py              # Main bot interface and handlers
├── SchedulerManager.py        # Quiz delivery engine with production features
├── LeaderboardManager.py      # Leaderboard and user tracking system
├── Auth.py                    # Google Drive authentication
├── MessageUtils.py            # Message utilities (if exists)
├── users.json                 # Local user tracking file (template)
├── schedules.db              # SQLite database for persistence
└── Quiz Files (.json)        # Quiz content files
```

## 🔧 Setup Instructions

### 1. Configure Google Drive Users File
1. Create a `users.json` file in your Google Drive with this structure:
```json
{
  "users": []
}
```

2. Get the file ID from Google Drive URL:
   - File URL: `https://drive.google.com/file/d/YOUR_FILE_ID_HERE/view`
   - Copy the `YOUR_FILE_ID_HERE` part

3. Set the file ID in the bot:
   ```
   /set_users_file YOUR_ACTUAL_GOOGLE_DRIVE_FILE_ID
   ```

### 2. Update Configuration
In `BrowseFile.py`, replace:
```python
USERS_JSON_FILE_ID = 'YOUR_USERS_JSON_FILE_ID_HERE'
```
With your actual Google Drive file ID.

### 3. Run the Bot
```bash
python BrowseFile.py
```

## 🎮 Bot Commands

### User Commands
- `/start` - Browse quiz files and schedule sessions
- `/schedules` - View your scheduled quiz sessions

### Admin/Test Commands  
- `/test_notification` - Test quiz delivery system
- `/test_quiz` - Test with available quiz files
- `/test_leaderboard` - Test leaderboard functionality
- `/set_users_file <file_id>` - Configure Google Drive users file
- `/failed_notifications` - Check failed delivery attempts

## 📊 Quiz Flow

### 1. Scheduling Process
1. **File Selection**: User browses Google Drive and selects quiz file
2. **Date Input**: User enters date (DD-MM-YYYY format)
3. **Time Input**: User enters time (HH:MM 24-hour format)  
4. **Timer Setting**: User sets poll duration (5-300 seconds)
5. **Confirmation**: User confirms the complete schedule

### 2. Quiz Delivery
1. **Initialization**: Bot starts quiz session and initializes leaderboard
2. **Question Delivery**: Each question is sent with:
   - Question text with A,B,C,D options
   - Interactive poll with custom timer
   - Non-anonymous voting for leaderboard tracking
3. **Answer Processing**: Bot tracks all poll answers automatically
4. **Explanation**: After timer expires, explanation is added to question
5. **Leaderboard**: Final leaderboard with participant rankings

## 🏆 Leaderboard Features

### User Tracking
- **Automatic Addition**: New participants added to Google Drive users.json
- **Duplicate Prevention**: Existing users not re-added  
- **Data Fields**: User ID, username, first name, last name, join date

### Leaderboard Display
- **Real-time Tracking**: Poll answers tracked automatically
- **Ranking System**: Sorted by correct answers, then total answered
- **Medal System**: 🥇🥈🥉 for top 3 participants
- **Statistics**: Shows correct/total answers and percentage

### Google Drive Integration
- **Auto-Download**: users.json downloaded before each quiz
- **Auto-Upload**: Updated user data uploaded after quiz completion
- **Conflict Prevention**: Thread-safe operations

## 🛡️ Production Features

### Error Handling
- **Telegram Timeouts**: Progressive timeout handling (30s to 120s)
- **Network Errors**: Exponential backoff retry (1s to 16s delays)
- **Fallback Messages**: User notification about server issues
- **Graceful Degradation**: Text questions if polls fail

### Reliability
- **SQLite Persistence**: All schedules stored in database
- **Retry Mechanisms**: Up to 5 attempts for critical operations
- **Dead Letter Queue**: Failed notifications logged for manual review
- **Thread Safety**: Background quiz delivery without blocking

### Performance
- **HTTP API Calls**: Direct Telegram API usage (no event loop issues)
- **Concurrent Processing**: Multiple quiz sessions supported
- **Memory Management**: Automatic cleanup of completed sessions
- **Database Optimization**: Indexed queries for fast retrieval

## 🔧 Technical Architecture
### Quiz Delivery Pipeline
```
Schedule Trigger → Download Quiz File → Initialize Leaderboard → 
Send Questions → Track Poll Answers → Generate Leaderboard → 
Upload User Data → Cleanup
```

### Error Recovery Chain
```
Primary Request → Timeout Handling → Retry with Backoff → 
Fallback Notification → Dead Letter Logging
```

### Data Flow
```
Google Drive ↔ Local Cache ↔ SQLite Database ↔ Leaderboard Manager ↔ 
Poll Tracking ↔ Quiz Delivery Engine
```

## 📈 Monitoring and Logs

### Console Output
- **Quiz Progress**: Real-time delivery status
- **Error Tracking**: Detailed error messages with context
- **Performance Metrics**: Response times and retry counts
- **User Activity**: Poll answer tracking and leaderboard updates

### Database Tables
- **schedules**: Quiz scheduling data with timer information
- **failed_notifications**: Dead letter queue for manual review

## 🎯 Advanced Features

### Dynamic Timer System
- **Custom Duration**: 5-300 second range per quiz
- **User Input**: Timer set during scheduling process
- **Display**: Timer shown in quiz start message and polls

### Poll Answer Tracking
- **Automatic Detection**: PollAnswerHandler captures all responses
- **User Identification**: Links poll answers to leaderboard entries  
- **Correct Answer Validation**: Compares against quiz data
- **Real-time Updates**: Leaderboard updated as answers come in

### Google Drive Management
- **Seamless Integration**: Transparent file operations
- **Version Control**: Always uses latest user data
- **Backup Strategy**: Local cache prevents data loss
- **Permission Handling**: Graceful fallbacks for access issues

## 🔍 Troubleshooting

### Common Issues
1. **"Poll not found"**: Poll tracking cleaned up - normal behavior
2. **"Users file not found"**: Run `/set_users_file` with correct ID  
3. **"Telegram timeout"**: Server delays handled automatically
4. **"Failed to upload"**: Check Google Drive permissions

### Debug Commands
- `/test_leaderboard` - Verify leaderboard generation
- `/failed_notifications` - Check delivery failures
- `/test_notification` - End-to-end system test

## 🎉 Success Indicators
- ✅ Quizzes delivered on time with custom timers
- ✅ All poll answers tracked in leaderboard  
- ✅ User data synchronized with Google Drive
- ✅ Error-free operation even with network issues
- ✅ Professional leaderboard display with rankings

This system is production-ready and handles all edge cases for reliable quiz delivery with comprehensive participant tracking!



Play Online
Play Social
East Australia Unranked Battlezone (EAU)
YASH
pass = 123



