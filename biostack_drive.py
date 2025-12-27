import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
CREDENTIALS_FILE = 'credentials.json'  # Same key from Step 1
TOKEN_FILE = 'drive_token.json'        # Specific token for Drive
SCOPES = ['https://www.googleapis.com/auth/drive.file']
FILENAME_LOCAL = 'biostack_prompt.txt'
FILENAME_DRIVE = 'BioStack_Weekly_Brief.txt' # The name inside Google Drive

def authenticate():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("👋 Need Drive Access. Opening Browser...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return creds

def upload_file():
    if not os.path.exists(FILENAME_LOCAL):
        print(f"❌ Error: {FILENAME_LOCAL} does not exist. Run analyst first.")
        return

    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)

    # 1. Search if file already exists in that folder (to avoid duplicates)
    query = f"name = '{FILENAME_DRIVE}' and '{FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])

    file_metadata = {
        'name': FILENAME_DRIVE,
        'parents': [FOLDER_ID]
    }
    media = MediaFileUpload(FILENAME_LOCAL, mimetype='text/plain')

    if files:
        # Update existing file
        file_id = files[0]['id']
        print(f"🔄 Updating existing file ({file_id})...")
        # For update, we don't send 'parents'
        update_metadata = {'name': FILENAME_DRIVE} 
        service.files().update(
            fileId=file_id, 
            body=update_metadata, 
            media_body=media
        ).execute()
        print("✅ Drive File Updated.")
    else:
        # Create new file
        print("🚀 Uploading new file to Drive...")
        service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id'
        ).execute()
        print("✅ Drive File Created.")

if __name__ == "__main__":
    if not FOLDER_ID:
        print("❌ Error: GOOGLE_DRIVE_FOLDER_ID not in .env")
    else:
        upload_file()