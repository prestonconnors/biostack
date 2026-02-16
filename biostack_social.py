import os
import json
import asyncio
import boto3
import argparse
import pandas as pd
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from twikit import Client, TooManyRequests

# Load environment variables
load_dotenv()

BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
HANDLES = [h.strip() for h in os.getenv('X_FOLLOW_LIST', '').split(',') if h.strip()]

TWITTER_USER = os.getenv('TWITTER_USERNAME')
TWITTER_EMAIL = os.getenv('TWITTER_EMAIL') 
TWITTER_PASS = os.getenv('TWITTER_PASSWORD')
COOKIE_FILE = 'twitter_cookies.json'

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--debug', action='store_true')
    return parser.parse_args()

def convert_cookies_to_dict(file_path):
    """
    Converts 'EditThisCookie' (List of Dicts) format to Twikit (Simple Dict) format.
    """
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            
        # Case 1: EditThisCookie Format (List)
        if isinstance(data, list):
            cookie_dict = {}
            for cookie in data:
                if 'name' in cookie and 'value' in cookie:
                    cookie_dict[cookie['name']] = cookie['value']
            return cookie_dict
            
        # Case 2: Already a Dict (Native Twikit)
        elif isinstance(data, dict):
            return data
            
    except Exception as e:
        print(f"   ⚠️ Error parsing cookies: {e}")
    return None

async def get_user_tweets(client, handle, days, debug=False):
    """
    Scrapes tweets for a specific handle using Twikit.
    """
    try:
        # 1. Get User ID
        user = await client.get_user_by_screen_name(handle)
        if debug:
            print(f"   found user id: {user.id}")

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        collected_tweets = []
        
        # 2. Fetch Tweets
        try:
            tweets = await user.get_tweets('Tweets', count=40)
        except Exception as e:
            print(f"   ⚠️ Could not fetch timeline (might be private/suspended): {e}")
            return []
        
        stop_scan = False
        
        while not stop_scan and tweets:
            for tweet in tweets:
                try:
                    # Parse timestamp (Twikit returns datetime object directly in recent versions)
                    # We handle both string and datetime just in case
                    if hasattr(tweet, 'created_at_datetime'):
                         ts_obj = tweet.created_at_datetime
                    else:
                         # Fallback for older versions/string responses
                         ts_obj = datetime.strptime(tweet.created_at, "%a %b %d %H:%M:%S %z %Y")
                    
                    if ts_obj < cutoff:
                        # Allow 24h buffer for pinned tweets before stopping
                        if ts_obj < cutoff - timedelta(days=1): 
                             stop_scan = True
                        continue

                    tweet_data = {
                        "ts": ts_obj.isoformat(),
                        "content": tweet.text.replace("\n", " "),
                        "likes": tweet.favorite_count,
                        "retweets": tweet.retweet_count,
                        "url": f"https://x.com/{handle}/status/{tweet.id}"
                    }
                    
                    collected_tweets.append(tweet_data)
                    if debug:
                        print(f"   [+] {ts_obj.strftime('%m-%d')} | {tweet.text[:40]}...")

                except Exception as e:
                    if debug: print(f"   Error parsing tweet: {e}")
                    continue
            
            if stop_scan:
                break
                
            try:
                tweets = await tweets.next()
            except Exception:
                break
                
        return collected_tweets

    except TooManyRequests as e:
        print(f"   ⚠️ Rate Limited on @{handle}: {e}")
        return []
    except Exception as e:
        print(f"   ❌ Error scraping @{handle}: {e}")
        return []

async def main():
    args = get_args()
    master_intel = {}
    
    # Initialize Client
    client = Client('en-US')

    # LOGIN LOGIC
    print("📡 Authenticating with X (Twikit)...")
    authenticated = False

    # 1. Try Cookies
    if os.path.exists(COOKIE_FILE):
        cookies = convert_cookies_to_dict(COOKIE_FILE)
        if cookies:
            client.set_cookies(cookies)
            print(f"   ✅ Loaded {len(cookies)} cookies from {COOKIE_FILE}")
            authenticated = True
        
    # 2. Verify / Fallback to Password
    try:
        # Simple test call to verify session
        # (This avoids a crash later if cookies are expired)
        try:
            await client.user() 
        except Exception:
            if TWITTER_USER and TWITTER_PASS:
                print("   🔄 Session expired. Performing full login...")
                await client.login(
                    auth_info_1=TWITTER_USER,
                    auth_info_2=TWITTER_EMAIL,
                    password=TWITTER_PASS
                )
                client.save_cookies(COOKIE_FILE)
                print("   ✅ Login success & cookies saved.")
                authenticated = True
            else:
                print("   ❌ Session expired and no credentials in .env")
                if not authenticated: return

    except Exception as e:
        print(f"   ❌ Authentication Error: {e}")
        # Proceed if we think we might still be good, otherwise return
        if not authenticated: return

    # PROCESSING LOOP
    for handle in HANDLES:
        print(f"📡 Processing @{handle}...")
        
        # Human pause
        await asyncio.sleep(2) 
        
        intel = await get_user_tweets(client, handle, args.days, debug=args.debug)
        
        if intel:
            master_intel[handle] = intel
            print(f"   ✅ Done: {len(intel)} tweets.")
        else:
            print(f"   ⚠️ No tweets found or access denied.")

    # UPLOAD TO S3
    if master_intel:
        try:
            key = f"social/social_intel_{datetime.now().strftime('%Y%m%d')}.json"
            s3 = boto3.client('s3')
            s3.put_object(
                Bucket=BUCKET_NAME, 
                Key=key, 
                Body=json.dumps(master_intel, indent=2)
            )
            print(f"🚀 SUCCESS: s3://{BUCKET_NAME}/{key}")
        except Exception as e:
            print(f"❌ S3 Upload Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
