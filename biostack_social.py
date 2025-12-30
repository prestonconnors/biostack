import os
import json
import requests
import boto3
import argparse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
BEARER_TOKEN = os.getenv('X_BEARER_TOKEN')
BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
HANDLES = os.getenv('X_FOLLOW_LIST', '').split(',')

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
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"❌ X API Error: {response.status_code} - {response.text}")
        return None
    return response.json()

def get_user_id(username):
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    data = twitter_request(url)
    return data['data']['id'] if data and 'data' in data else None

def fetch_tweets(user_id, start_date):
    url = f"https://api.twitter.com/2/users/{user_id}/tweets"
    params = {
        "start_time": start_date.isoformat(),
        "tweet.fields": "created_at,text,public_metrics,entities",
        "max_results": 20  # Free tier limits
    }
    data = twitter_request(url, params)
    return data.get('data', []) if data else []

def main():
    args = get_args()
    s3 = get_s3_client()
    
    start_date = (datetime.now(timezone.utc) - timedelta(days=args.days))
    all_social_data = {}

    print(f"🐦 Fetching tweets from {len(HANDLES)} accounts for the last {args.days} days...")

    for handle in HANDLES:
        handle = handle.strip()
        if not handle: continue
        
        user_id = get_user_id(handle)
        if user_id:
            tweets = fetch_tweets(user_id, start_date)
            all_social_data[handle] = tweets
            print(f"   ✅ @{handle}: Found {len(tweets)} tweets.")

    # Save to S3
    timestamp = datetime.now().strftime('%Y%m%d')
    key = f"social/tweets_{timestamp}.json"
    
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=json.dumps(all_social_data),
        ContentType='application/json'
    )
    print(f"🚀 SUCCESS: Uploaded to s3://{BUCKET_NAME}/{key}")

if __name__ == "__main__":
    main()