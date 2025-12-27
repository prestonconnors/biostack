import os
import json
import requests
import boto3
import argparse
import secrets
import time
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

# Using V2 Endpoints
ENDPOINTS = {
    "cycles": "https://api.prod.whoop.com/developer/v2/cycle",
    "recovery": "https://api.prod.whoop.com/developer/v2/recovery",
    "sleep": "https://api.prod.whoop.com/developer/v2/activity/sleep",
    "workouts": "https://api.prod.whoop.com/developer/v2/activity/workout"
}

# IMPORTANT: 'offline' scope allows for unattended 24/7 background refreshing
SCOPES = "read:recovery read:cycles read:sleep read:workout offline"

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
    """
    Whoop rotates refresh tokens. We must save the entire response 
    to capture the NEW refresh_token every time.
    """
    # Safety: Calculate specific expire time
    if 'expires_in' in token_data:
        # Set expire time to 60 seconds BEFORE actual expiry to avoid race conditions
        token_data['expires_at'] = (datetime.now() + timedelta(seconds=token_data['expires_in'] - 60)).timestamp()
    
    # Merge with existing data if the new response is partial (just in case)
    existing = load_tokens() or {}
    final_data = {**existing, **token_data}
    
    with open(TOKEN_FILE, 'w') as f:
        json.dump(final_data, f)

def load_tokens():
    if not os.path.exists(TOKEN_FILE): return None
    try:
        with open(TOKEN_FILE, 'r') as f: return json.load(f)
    except:
        return None

def refresh_access_token():
    tokens = load_tokens()
    if not tokens or 'refresh_token' not in tokens:
        raise Exception("No refresh token found. Please delete whoop_tokens.json and re-run manually.")
        
    print("🔄 performing Token Refresh...")
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': tokens['refresh_token'],
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': SCOPES
    }
    
    r = requests.post(TOKEN_URL, data=payload)
    if r.status_code != 200:
        print(f"CRITICAL: Refresh failed {r.status_code}. Response: {r.text}")
        raise Exception("Token Refresh Failed. Authorization chain broken.")
    
    new_data = r.json()
    save_tokens(new_data)
    print("✅ Refresh Success.")
    return new_data['access_token']

def get_valid_token():
    """ Determines if we need to refresh or just return current token """
    tokens = load_tokens()
    
    # 1. First Run logic
    if not tokens:
        return perform_initial_auth()
    
    # 2. Check Time
    now_ts = datetime.now().timestamp()
    expires_at = tokens.get('expires_at', 0)
    
    if now_ts >= expires_at:
        print("⏳ Token Expired. Refreshing...")
        return refresh_access_token()
    
    return tokens['access_token']

def perform_initial_auth():
    print("\n⚠️ NO VALID TOKEN FOUND.")
    state_token = secrets.token_urlsafe(16)
    
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPES,
        'state': state_token
    }
    
    req = requests.Request('GET', AUTH_URL, params=params).prepare()
    print(f"ACTION REQUIRED:\n1. Open this URL: {req.url}\n2. Login and Authorize.\n3. Copy the CODE from the localhost URL.")
    
    code = input("Paste Code here: ").strip()
    if "code=" in code: code = code.split("code=")[1]
    if "&" in code: code = code.split("&")[0]

    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI
    }
    
    r = requests.post(TOKEN_URL, data=payload)
    if r.status_code != 200:
        raise Exception(f"Auth Failed: {r.text}")

    save_tokens(r.json())
    return r.json()['access_token']

def make_request_with_retry(url, params):
    """
    Wrapper to handle 401s (expired tokens) gracefully by refreshing and retrying once.
    """
    token = get_valid_token()
    headers = {'Authorization': f'Bearer {token}'}
    
    res = requests.get(url, headers=headers, params=params)
    
    # CATCH 401: Token expired mid-script or on server?
    if res.status_code == 401:
        print("⚠️ 401 Unauthorized caught. Force-refreshing token and retrying...")
        token = refresh_access_token()
        headers = {'Authorization': f'Bearer {token}'}
        res = requests.get(url, headers=headers, params=params)
        
    return res

def fetch_all_metrics(start, end):
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    print(f"📡 Whoop V2 Fetch: {start_str} -> {end_str}")
    
    combined_data = {}
    
    for key, url in ENDPOINTS.items():
        print(f"   Downloading '{key}'...", end=" ")
        params = {'start': start_str, 'end': end_str, 'limit': 25} 
        
        try:
            all_records = []
            next_token = None
            
            while True:
                if next_token:
                    params['nextToken'] = next_token
                
                # USE THE ROBUST REQUESTER
                res = make_request_with_retry(url, params)
                
                if res.status_code == 429:
                    print("RATE LIMITED. Sleeping 5s...", end=" ")
                    time.sleep(5)
                    continue
                    
                if res.status_code != 200:
                    print(f"❌ Error {res.status_code}: {res.text}")
                    break
                    
                page_data = res.json()
                records = page_data.get('records', [])
                all_records.extend(records)
                
                next_token = page_data.get('next_token')
                if not next_token:
                    break
            
            combined_data[key] = all_records
            print(f"✅ Got {len(all_records)}")
            
        except Exception as e:
            print(f"⚠️ Exception: {e}")
            combined_data[key] = []

    return combined_data

def upload_to_aws(data, start, end):
    s3 = get_s3_client()
    key = f"whoop/whoop_FULL_{start.strftime('%Y%m%d')}_to_{end.strftime('%Y%m%d')}.json"
    
    s3.put_object(
        Bucket=BUCKET_NAME, 
        Key=key, 
        Body=json.dumps(data), 
        ContentType='application/json'
    )
    print(f"🚀 SUCCESS! Saved: s3://{BUCKET_NAME}/{key}")

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

    start_date = start_date.replace(hour=0, minute=0, second=0).astimezone(timezone.utc)
    end_date = end_date.replace(hour=23, minute=59, second=59).astimezone(timezone.utc)
    
    try:
        data = fetch_all_metrics(start_date, end_date)
        upload_to_aws(data, start_date, end_date)
    except Exception as e:
        print(f"Script Error: {e}")

if __name__ == "__main__":
    main()