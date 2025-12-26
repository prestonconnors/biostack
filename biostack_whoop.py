import os
import json
import requests
import boto3
import secrets
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load sensitive variables from .env file
load_dotenv()

# --- CONFIGURATION ---
CLIENT_ID = os.getenv('WHOOP_CLIENT_ID')
CLIENT_SECRET = os.getenv('WHOOP_CLIENT_SECRET')
BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
REDIRECT_URI = 'http://localhost'
TOKEN_FILE = 'whoop_tokens.json'

# API Endpoints
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
DATA_URL = "https://api.prod.whoop.com/developer/v1/cycle"

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )

def save_tokens(token_data):
    token_data['expires_at'] = (datetime.now() + timedelta(seconds=token_data['expires_in'])).timestamp()
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_data, f)

def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, 'r') as f:
        return json.load(f)

def authenticate():
    """Handles OAuth Flow."""
    tokens = load_tokens()

    # Scenario 1: Refresh Token
    if tokens:
        if datetime.now().timestamp() < tokens['expires_at']:
            return tokens['access_token']
        
        print("Token expired. Refreshing...")
        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': tokens['refresh_token'],
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'scope': 'read:recovery read:cycles read:sleep read:workout'
        }
        r = requests.post(TOKEN_URL, data=payload)
        if r.status_code == 200:
            new_tokens = r.json()
            save_tokens(new_tokens)
            return new_tokens['access_token']
        else:
            print("Refresh failed. Restarting auth flow...")

    # Scenario 2: Initial Login (Manual)
    # Generate a random state string for security (required by Whoop now)
    secure_random_state = secrets.token_urlsafe(16)
    
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': 'read:recovery read:cycles read:sleep read:workout',
        'state': secure_random_state
    }
    
    # Generate the link
    auth_request_url = requests.Request('GET', AUTH_URL, params=params).prepare().url
    
    print("\n--- FIRST RUN AUTHENTICATION ---")
    print(f"1. Click this URL to authorize: \n{auth_request_url}")
    print("2. When 'localhost refused to connect' appears, look at the URL bar.")
    print("3. COPY the text specifically between 'code=' and '&state'.")
    
    auth_code = input("Paste ONLY the code here: ").strip()

    # Clean the input in case you pasted the whole URL by accident
    if "code=" in auth_code:
        auth_code = auth_code.split("code=")[1]
    if "&" in auth_code:
        auth_code = auth_code.split("&")[0]

    # Exchange code for token
    payload = {
        'grant_type': 'authorization_code',
        'code': auth_code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI
    }
    
    r = requests.post(TOKEN_URL, data=payload)
    if r.status_code != 200:
        raise Exception(f"Auth Failed: {r.text}")
    
    token_data = r.json()
    save_tokens(token_data)
    return token_data['access_token']

def fetch_data(days_back=7):
    token = authenticate()
    
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days_back)
    
    print(f"Fetching Whoop data from {start_date.date()} to {end_date.date()}...")
    
    headers = {'Authorization': f'Bearer {token}'}
    params = {
        'start': start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        'end': end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        'limit': 25 
    }
    
    response = requests.get(DATA_URL, headers=headers, params=params)
    if response.status_code != 200:
        raise Exception(f"API Error: {response.text}")
    
    return response.json()

def upload_to_aws(data, days_back):
    s3 = get_s3_client()
    timestamp = datetime.now().strftime('%Y-%m-%d')
    filename = f"whoop/whoop_data_{timestamp}_lookback{days_back}d.json"
    
    try:
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=filename,
            Body=json.dumps(data),
            ContentType='application/json'
        )
        print(f"✅ Success! Data saved to S3: s3://{BUCKET_NAME}/{filename}")
    except Exception as e:
        print(f"❌ AWS Upload Failed: {str(e)}")

def main():
    DAYS_TO_ANALYZE = 7
    try:
        data = fetch_data(DAYS_TO_ANALYZE)
        record_count = len(data) if isinstance(data, list) else len(data.get('records', []))
        print(f"Retrieved {record_count} cycle records.")
        upload_to_aws(data, DAYS_TO_ANALYZE)
    except Exception as e:
        print(f"Script Error: {e}")

if __name__ == "__main__":
    main()