import os
import json
import boto3
import argparse
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Google API Imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

# --- CONFIGURATION ---
SPREADSHEET_ID = os.getenv('GOOGLE_SPREADSHEET_ID')
RANGE_NAME = os.getenv('GOOGLE_SHEET_RANGE')  
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, help='Start Date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End Date YYYY-MM-DD')
    parser.add_argument('--days', type=int, default=7, help='Days back (default: 7)')
    return parser.parse_args()

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-east-1'
    )

def authenticate_google():
    """ Handles Google Login and Token management """
    creds = None
    # 1. Look for existing token
    if os.path.exists('google_token.json'):
        creds = Credentials.from_authorized_user_file('google_token.json', SCOPES)
    
    # 2. Refresh or New Login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing Google Token...")
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise Exception("❌ Missing credentials.json. Cannot Authenticate.")
            
            print("👋 First Run: Opening Browser for Auth...")
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Save token for next time
        with open('google_token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def fetch_sheet_data(service):
    if not SPREADSHEET_ID:
        raise Exception("❌ Error: GOOGLE_SPREADSHEET_ID not found in .env file")
    
    print(f"📖 Reading Google Sheet: {RANGE_NAME}...")
    try:
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        rows = result.get('values', [])
        return rows
    except Exception as e:
        raise Exception(f"Failed to read sheet. Check ID and Permissions. Error: {e}")

def process_and_upload(rows, start_date, end_date):
    if not rows:
        print("⚠️ Sheet is empty or range is invalid.")
        return

    # Row 0 is Headers
    headers = rows[0]
    data = rows[1:]
    
    clean_data = []
    for r in data:
        # Securely zip headers to values
        item = {k.strip(): v for k, v in zip(headers, r)}
        clean_data.append(item)
    
    df = pd.DataFrame(clean_data)
    
    # 1. Find Date Column
    date_col = None
    for col in df.columns:
        if 'date' in col.lower():
            date_col = col
            break
            
    if date_col:
        # 2. Filter by Date
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        
        # Drop rows where date failed to parse
        df = df.dropna(subset=[date_col])

        mask = (df[date_col] >= start_date) & (df[date_col] <= end_date)
        df_filtered = df.loc[mask].copy()
        
        count = len(df_filtered)
        print(f"   Filtering: Found {count} logs between {start_date.date()} and {end_date.date()}")
        
        if count > 0:
            final_data = df_filtered.fillna("").astype(str).to_dict(orient='records')
            
            s3 = get_s3_client()
            key = f"vitals/vitals_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}.json"
            
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=key,
                Body=json.dumps(final_data),
                ContentType='application/json'
            )
            print(f"✅ Success: s3://{BUCKET_NAME}/{key}")
        else:
            print("⚠️ No data matches that specific date range.")
    else:
        print("❌ Error: Column 'Date' not found in spreadsheet.")

def main():
    args = get_args()
    
    if args.end:
        end_date = datetime.strptime(args.end, '%Y-%m-%d')
    else:
        end_date = datetime.now()

    if args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
    else:
        start_date = end_date - timedelta(days=args.days)
    
    try:
        creds = authenticate_google()
        service = build('sheets', 'v4', credentials=creds)
        
        rows = fetch_sheet_data(service)
        process_and_upload(rows, start_date, end_date)
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()