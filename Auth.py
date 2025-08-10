import os
import pickle
from datetime import datetime
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/drive']

def check_token_status():
    """Check token expiration status"""
    if not os.path.exists('token.pickle'):
        return "No token file found"
    
    try:
        with open('token.pickle', 'rb') as token_file:
            creds = pickle.load(token_file)
        
        if not creds:
            return "Invalid credentials"
        
        if creds.valid:
            if hasattr(creds, 'expiry') and creds.expiry:
                remaining = creds.expiry - datetime.utcnow()
                return f"Token valid, expires in: {remaining}"
            else:
                return "Token valid, no expiry info"
        elif creds.expired:
            if hasattr(creds, 'expiry') and creds.expiry:
                expired_ago = datetime.utcnow() - creds.expiry
                return f"Token expired {expired_ago} ago"
            else:
                return "Token expired, no expiry info"
        else:
            return "Token not valid"
    except Exception as e:
        return f"Error checking token: {e}"

def authenticate():
    creds = None

    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token_file:
            creds = pickle.load(token_file)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("🔄 Refreshing expired Google Drive token...")
                print(f"📊 Token status: {check_token_status()}")
                creds.refresh(Request())
                print("✅ Token refreshed successfully")
                
                # Show new expiration
                if hasattr(creds, 'expiry') and creds.expiry:
                    print(f"🕐 New token expires at: {creds.expiry}")
                
                # Save the refreshed token
                with open('token.pickle', 'wb') as token_file:
                    pickle.dump(creds, token_file)
            except Exception as e:
                print(f"❌ Token refresh failed: {e}")
                print("🔄 Starting new authentication flow...")
                creds = None  # Force new authentication
        
        if not creds or not creds.valid:
            print("🔐 Starting Google Drive authentication...")
            try:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
                print("✅ Authentication successful")
                
                # Show expiration info
                if hasattr(creds, 'expiry') and creds.expiry:
                    print(f"🕐 Token expires at: {creds.expiry}")
                
                # Save the new token
                with open('token.pickle', 'wb') as token_file:
                    pickle.dump(creds, token_file)
            except Exception as e:
                print(f"❌ Authentication failed: {e}")
                raise e
    else:
        # Token is valid, show status
        if hasattr(creds, 'expiry') and creds.expiry:
            remaining = creds.expiry - datetime.utcnow()
            print(f"✅ Token valid, expires in: {remaining}")

    return build('drive', 'v3', credentials=creds)