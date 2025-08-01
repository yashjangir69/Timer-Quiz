"""
Google Drive Handler for Quiz Bot
Handles all Google Drive operations including folder navigation and file operations
"""

import os
import json
import pickle
import logging
from typing import List, Dict, Any, Optional, Tuple
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaIoBaseDownload
import io

logger = logging.getLogger(__name__)

class DriveHandler:
    def __init__(self):
        self.SCOPES = ['https://www.googleapis.com/auth/drive']
        self.service = None
        self.quizzes_folder_id = None
        self._authenticate()
        self._find_quizzes_folder()

    def _authenticate(self):
        """Authenticate with Google Drive API"""
        creds = None
        
        # Load existing token
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
        
        # If there are no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save credentials for future use
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        
        self.service = build('drive', 'v3', credentials=creds)
        logger.info("Google Drive authenticated successfully")

    def _find_quizzes_folder(self):
        """Find the main Quizzes folder ID"""
        try:
            results = self.service.files().list(
                q="name='quizzes' and mimeType='application/vnd.google-apps.folder'",
                fields="files(id, name)"
            ).execute()
            
            items = results.get('files', [])
            if items:
                self.quizzes_folder_id = items[0]['id']
                logger.info(f"Found quizzes folder with ID: {self.quizzes_folder_id}")
            else:
                logger.error("quizzes folder not found in Google Drive")
                raise Exception("Quizzes folder not found")
        except Exception as e:
            logger.error(f"Error finding Quizzes folder: {e}")
            raise

    def get_folder_contents(self, folder_id: str = None) -> List[Dict[str, Any]]:
        """Get contents of a folder (subfolders and files)"""
        if folder_id is None:
            folder_id = self.quizzes_folder_id
        
        try:
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType)",
                orderBy="name"
            ).execute()
            
            items = results.get('files', [])
            contents = []
            
            for item in items:
                is_folder = item['mimeType'] == 'application/vnd.google-apps.folder'
                is_json = item['name'].endswith('.json')
                
                if is_folder or is_json:
                    contents.append({
                        'id': item['id'],
                        'name': item['name'],
                        'type': 'folder' if is_folder else 'file',
                        'is_quiz': is_json
                    })
            
            logger.info(f"Retrieved {len(contents)} items from folder {folder_id}")
            return contents
            
        except Exception as e:
            logger.error(f"Error getting folder contents: {e}")
            return []

    def download_quiz_file(self, file_id: str, filename: str) -> Optional[Dict[str, Any]]:
        """Download and parse a quiz JSON file"""
        try:
            request = self.service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            # Parse JSON content
            fh.seek(0)
            content = fh.read().decode('utf-8')
            quiz_data = json.loads(content)
            
            # Save locally for processing
            local_path = f"temp_{filename}"
            with open(local_path, 'w', encoding='utf-8') as f:
                json.dump(quiz_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Downloaded quiz file: {filename}")
            return quiz_data
            
        except Exception as e:
            logger.error(f"Error downloading quiz file {filename}: {e}")
            return None

    def get_breadcrumb_path(self, folder_id: str) -> str:
        """Get the full path to a folder for display purposes"""
        if folder_id == self.quizzes_folder_id:
            return "quizzes"
        
        path_parts = []
        current_id = folder_id
        
        try:
            while current_id and current_id != self.quizzes_folder_id:
                file_info = self.service.files().get(
                    fileId=current_id,
                    fields="name, parents"
                ).execute()
                
                path_parts.append(file_info['name'])
                parents = file_info.get('parents', [])
                current_id = parents[0] if parents else None
            
            path_parts.append("quizzes")
            return " / ".join(reversed(path_parts))
            
        except Exception as e:
            logger.error(f"Error getting breadcrumb path: {e}")
            return "quizzes"

    def update_users_file(self, new_users: Dict[str, Dict[str, str]]):
        """Update users.json file on Google Drive"""
        try:
            # First, try to find existing users.json file
            results = self.service.files().list(
                q="name='users.json' and trashed=false",
                fields="files(id, name)"
            ).execute()
            
            existing_users = {}
            file_id = None
            
            if results.get('files'):
                file_id = results['files'][0]['id']
                # Download existing file
                request = self.service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                
                fh.seek(0)
                content = fh.read().decode('utf-8')
                existing_users = json.loads(content) if content.strip() else {}
            
            # Merge new users (only add new ones)
            for user_id, user_data in new_users.items():
                if user_id not in existing_users:
                    existing_users[user_id] = user_data
            
            # Save updated users data
            users_json = json.dumps(existing_users, ensure_ascii=False, indent=2)
            
            # Create/update file on Drive
            from googleapiclient.http import MediaIoBaseUpload
            
            media = MediaIoBaseUpload(
                io.BytesIO(users_json.encode('utf-8')),
                mimetype='application/json'
            )
            
            if file_id:
                # Update existing file
                self.service.files().update(
                    fileId=file_id,
                    media_body=media
                ).execute()
            else:
                # Create new file
                file_metadata = {'name': 'users.json'}
                self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()
            
            logger.info(f"Updated users.json with {len(new_users)} new users")
            
        except Exception as e:
            logger.error(f"Error updating users file: {e}")

    def cleanup_temp_files(self, pattern: str = "temp_*.json"):
        """Clean up temporary quiz files"""
        import glob
        try:
            temp_files = glob.glob(pattern)
            for file in temp_files:
                os.remove(file)
                logger.info(f"Cleaned up temp file: {file}")
        except Exception as e:
            logger.error(f"Error cleaning up temp files: {e}")
