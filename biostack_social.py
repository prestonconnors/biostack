import os
import json
import requests
import boto3
import argparse
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
BEARER_TOKEN = os.getenv('X_BEARER_TOKEN')
BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
HANDLES = [h.strip() for h in os.getenv('X_FOLLOW_LIST', '').split(',') if h.strip()]

# Static Cache to save API calls (X API IDs don't change)
# Fetching IDs via /users/by/username/ costs 1 rate-limit credit. 
ID_CACHE = {
    "bryan_johnson": "216035041",
    "hubermanlab": "1274530006325555201",
    "peterattiamd": "468305374"
}

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=7, help='Days back to fetch')
    return parser.parse_args()

def get_s3_client():
    return boto3.client('s3', 
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-east-1'
    )

def twitter_request(url, params=None):
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    
    # Simple retry logic for 429s
    for attempt in range(3):
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            wait = 15 * (attempt + 1) # Wait longer each time
            print(f"⚠️ Rate limited. Sleeping {wait}s...")
            time.sleep(wait)
        else:
            print(f"❌ X API Error: {response.status_code} - {response.text}")
            return None
    return None

def get_user_id(username):
    # Use cache first to save rate limits
    if username.lower() in ID_CACHE:
        return ID_CACHE[username.lower()]
    
    print(f"🔍 Looking up ID for @{username}...")
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    data = twitter_request(url)
    if data and 'data' in data:
        uid = data['data']['id']
        print(f"   (ID found: {uid})")
        return uid
    return None

def fetch_tweets(user_id, start_date):
    # Format: 2024-01-01T00:00:00Z (RFC3339)
    # X API fails if microseconds or timezone offsets (+00:00) are present
    start_str = start_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    url = f"https://api.twitter.com/2/users/{user_id}/tweets"
    params = {
        "start_time": start_str,
        "tweet.fields": "created_at,text",
        "max_results": 20  # Minimum allowed by API
    }
    
    data = twitter_request(url, params)
    return data.get('data', []) if data else []

def main():
    args = get_args()
    s3 = get_s3_client()
    
    # Calculate UTC Start Time
    start_date = (datetime.now(timezone.utc) - timedelta(days=args.days))
    all_social_data = {}

    print(f"🐦 Fetching tweets from {len(HANDLES)} accounts for the last {args.days} days...")

    for handle in HANDLES:
        user_id = get_user_id(handle)
        
        if user_id:
            tweets = fetch_tweets(user_id, start_date)
            all_social_data[handle] = tweets
            print(f"   ✅ @{handle}: Found {len(tweets)} tweets.")
            
            # mandatory rest period to respect small rate limits
            time.sleep(2) 
        else:
            print(f"   ⏭️ Skipping @{handle} (No ID found)")

    # Save to S3 (even if dict is empty)
    timestamp = datetime.now().strftime('%Y%m%d')
    key = f"social/tweets_{timestamp}.json"
    
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=json.dumps(all_social_data),
        ContentType='application/json'
    )
    print(f"\n🚀 SUCCESS: Logged to S3 key: {key}")

if __name__ == "__main__":
    main()