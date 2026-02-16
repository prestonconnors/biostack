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

# Twikit requires credentials if cookies expire. 
# Add these to your .env file for robustness.
TWITTER_USER = os.getenv('TWITTER_USERNAME')
TWITTER_EMAIL = os.getenv('TWITTER_EMAIL') 
TWITTER_PASS = os.getenv('TWITTER_PASSWORD')
COOKIE_FILE = 'twitter_cookies.json'

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--debug', action='store_true')
    return parser.parse_args()

async def get_user_tweets(client, handle, days, debug=False):
    """
    Scrapes tweets for a specific handle using Twikit.
    """
    try:
        # 1. Get User ID from Handle
        user = await client.get_user_by_screen_name(handle)
        if debug:
            print(f"   found user id: {user.id}")

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        collected_tweets = []
        
        # 2. Fetch Tweets (Batching handled by library)
        # We fetch slightly more to ensure we cover the date range
        tweets = await user.get_tweets('Tweets', count=40)
        
        stop_scan = False
        
        while not stop_scan:
            if not tweets:
                break

            for tweet in tweets:
                # Convert tweet time to UTC datetime
                # Twikit returns string usually, dependent on version. 
                # Assuming standard format or checking object properties.
                try:
                    # Twikit datetime is usually available directly or needs parsing
                    if hasattr(tweet, 'created_at_datetime'):
                         ts_obj = tweet.created_at_datetime
                    else:
                         ts_obj = datetime.strptime(tweet.created_at, "%a %b %d %H:%M:%S %z %Y")
                    
                    if ts_obj < cutoff:
                        # If we hit a tweet older than cutoff and it's not pinned, stop.
                        # (Pinned logic is tricky in API, but usually safe to just check date)
                        if ts_obj < cutoff - timedelta(days=1): # Buffer
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
                
            # Fetch next page
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
    try:
        if os.path.exists(COOKIE_FILE):
            client.load_cookies(COOKIE_FILE)
            print(f"   ✅ Loaded session from {COOKIE_FILE}")
        
        # Verify login or full login if cookies missing/invalid
        # We attempt a call; if it fails, we login with password
        try:
            # Simple check to see if we are valid (get own user)
            # Some versions allow client.user() check
            pass 
        except:
            if TWITTER_USER and TWITTER_PASS:
                print("   🔄 Cookies failed/missing, performing full login...")
                await client.login(
                    auth_info_1=TWITTER_USER,
                    auth_info_2=TWITTER_EMAIL,
                    password=TWITTER_PASS
                )
                client.save_cookies(COOKIE_FILE)
                print("   ✅ Login success & cookies saved.")
            else:
                print("   ❌ No valid cookies and no credentials in .env")
                return

    except Exception as e:
        print(f"   ❌ Authentication Failed: {e}")
        return

    # PROCESSING LOOP
    for handle in HANDLES:
        print(f"📡 Processing @{handle}...")
        
        # Add a small random pause to behave like a human
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