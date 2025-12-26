import os
import json
import requests
import boto3
import argparse
import secrets
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
CLIENT_ID = os.getenv('WHOOP_CLIENT_ID')
CLIENT_SECRET = os.getenv('WHOOP_CLIENT_SECRET')
BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
REDIRECT_URI = 'http://localhost'
TOKEN_FILE = 'whoop_tokens.json'
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
DATA_URL = "https://api.prod.whoop.com/developer/v1/cycle"

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, help='Start Date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End Date YYYY-MM-DD')
    parser.add_argument('--days', type=int, default=7, help='Days back')
    return parser.parse_args()

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-east-1'
    )

def save_tokens(token_data):
    token_data['expires_at'] = (datetime.now() + timedelta(seconds=token_data['expires_in'])).timestamp()
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_data, f)

def load_tokens():
    if not os.path.exists(TOKEN_FILE): return None
    with open(TOKEN_FILE, 'r') as f: return json.load(f)

def authenticate():
    tokens = load_tokens()
    # 1. Refresh existing token
    if tokens:
        if datetime.now().timestamp() < tokens.get('expires_at', 0):
            return tokens['access_token']
        
        # print("Refreshing token...")
        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': tokens['refresh_token'],
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'scope': 'read:recovery read:cycles read:sleep read:workout'
        }
        try:
            r = requests.post(TOKEN_URL, data=payload)
            r.raise_for_status()
            new_tokens = r.json()
            save_tokens(new_tokens)
            return new_tokens['access_token']
        except:
            print("Refresh failed. Re-auth required.")

    # 2. New Login
    state_token = secrets.token_urlsafe(16)
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': 'read:recovery read:cycles read:sleep read:workout',
        'state': state_token
    }
    url = requests.Request('GET', AUTH_URL, params=params).prepare().url
    print(f"\nACTION REQUIRED:\n1. Click: {url}\n2. Paste code:")
    code = input("Code: ").strip()
    
    # Extract clean code
    if "code=" in code: code = code.split("code=")[1]
    if "&" in code: code = code.split("&")[0]

    r = requests.post(TOKEN_URL, data={
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI
    })
    
    token_data = r.json()
    save_tokens(token_data)
    return token_data['access_token']

def fetch_data(start, end):
    token = authenticate()
    headers = {'Authorization': f'Bearer {token}'}
    
    # Whoop expects ISO strings 2024-01-01T00:00:00.000Z
    # Start and End here are datetime objects
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    print(f"Fetching Whoop: {start.date()} -> {end.date()}")
    
    params = {'start': start_str, 'end': end_str, 'limit': 25}
    res = requests.get(DATA_URL, headers=headers, params=params)
    if res.status_code != 200:
        raise Exception(res.text)
    
    return res.json()

def upload_to_aws(data, start, end):
    s3 = get_s3_client()
    key = f"whoop/whoop_{start.strftime('%Y%m%d')}_to_{end.strftime('%Y%m%d')}.json"
    s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=json.dumps(data), ContentType='application/json')
    print(f"✅ Success: s3://{BUCKET_NAME}/{key}")

def main():
    args = get_args()
    
    # Date Logic
    if args.end:
        end_date = datetime.strptime(args.end, '%Y-%m-%d')
    else:
        end_date = datetime.now()

    if args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
    else:
        start_date = end_date - timedelta(days=args.days)

    # Ensure valid Whoop timestamps (UTC)
    start_date = start_date.replace(hour=0, minute=0, second=0).astimezone(timezone.utc)
    end_date = end_date.replace(hour=23, minute=59, second=59).astimezone(timezone.utc)
    
    try:
        data = fetch_data(start_date, end_date)
        upload_to_aws(data, start_date, end_date)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()