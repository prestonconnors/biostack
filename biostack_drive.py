import os
import argparse
import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'drive_token.json'
SCOPES = ['https://www.googleapis.com/auth/drive.file']
FILENAME_LOCAL = 'biostack_prompt.txt'

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, help='Start Date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End Date YYYY-MM-DD')
    parser.add_argument('--days', type=int, default=7, help='Days back')
    return parser.parse_args()

def calculate_dates(args):
    if args.end:
        end_date = datetime.datetime.strptime(args.end, '%Y-%m-%d')
    else:
        end_date = datetime.datetime.now()

    if args.start:
        start_date = datetime.datetime.strptime(args.start, '%Y-%m-%d')
    else:
        # Default match logic of Analyst
        start_date = end_date - datetime.timedelta(days=args.days)
    
    return start_date, end_date

def authenticate():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("👋 First Run: Authenticating Google Drive...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return creds

def upload_file(start_date, end_date):
    if not os.path.exists(FILENAME_LOCAL):
        print(f"❌ Error: {FILENAME_LOCAL} missing. Run analyst script first.")
        return

    # 1. Generate Dynamic Filename
    # Format: BioStack_Brief_2025-01-01_to_2025-01-08.txt
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    target_filename = f"BioStack_Brief_{start_str}_to_{end_str}.txt"

    creds = authenticate()
    service = build('drive', 'v3', credentials=creds)

    # 2. Check if THIS specific week already exists (to prevent duplicates if run twice)
    # query looks for exact name inside specific folder
    query = f"name = '{target_filename}' and '{FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])

    file_metadata = {
        'name': target_filename,
        'parents': [FOLDER_ID]
    }
    media = MediaFileUpload(FILENAME_LOCAL, mimetype='text/plain')

    if files:
        # Update existing
        file_id = files[0]['id']
        print(f"🔄 Overwriting existing log: {target_filename}...")
        service.files().update(
            fileId=file_id, 
            media_body=media
        ).execute()
        print("✅ Success: Drive file updated.")
    else:
        # Create new
        print(f"🚀 Uploading new log: {target_filename}...")
        service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id'
        ).execute()
        print("✅ Success: Drive file created.")

def main():
    if not FOLDER_ID:
        print("❌ Error: GOOGLE_DRIVE_FOLDER_ID not set in .env")
        return

    args = get_args()
    start, end = calculate_dates(args)
    
    upload_file(start, end)

if __name__ == "__main__":
    main()