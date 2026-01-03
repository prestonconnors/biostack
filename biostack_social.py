import os
import json
import time
import boto3
import argparse
import pandas as pd
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

# --- CONFIG ---
BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
HANDLES = [h.strip() for h in os.getenv('X_FOLLOW_LIST', '').split(',') if h.strip()]

def get_args():
    parser = argparse.ArgumentParser(description="BioStack Social Gatherer (Expert Intel Scraper)")
    parser.add_argument('--days', type=int, default=7, help="How many days back to search")
    parser.add_argument('--visible', action='store_true', help="Show browser (laptop debugging)")
    parser.add_argument('--no-replies', action='store_true', help="Fetch main tweets ONLY (disables /with_replies)")
    return parser.parse_args()

def setup_driver(headless=True):
    chrome_options = Options()
    
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
    
    # Advanced Anti-Fingerprinting
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Obscure the automation identity
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def inject_cookies(driver):
    cookie_path = 'twitter_cookies.json'
    if not os.path.exists(cookie_path):
        raise Exception(f"❌ {cookie_path} missing! Export JSON cookies from your laptop Chrome first.")
    
    print("🌐 Establishing context at x.com...")
    driver.get("https://x.com")
    time.sleep(3)

    with open(cookie_path, 'r') as f:
        cookies = json.load(f)

    print(f"🍪 Injecting {len(cookies)} cookies...")
    for cookie in cookies:
        clean_cookie = {
            'name': cookie['name'],
            'value': cookie['value'],
            'domain': cookie['domain'],
            'path': cookie.get('path', '/'),
            'secure': cookie.get('secure', True)
        }
        try:
            driver.add_cookie(clean_cookie)
        except:
            pass # Standard behavior for some incompatible headers

    print("🔄 Session injection complete. Verifying access...")
    driver.get("https://x.com/home")
    time.sleep(5)
    
    if "login" in driver.current_url:
        print("❌ Login check failed. Re-export cookies or check X account status.")
        return False
    return True

def scrape_handle(driver, handle, days, fetch_replies=True):
    # Set URL: Expert activity often happens in the 'with_replies' tab
    base_url = f"https://x.com/{handle}"
    url = f"{base_url}/with_replies" if fetch_replies else base_url
    
    print(f"📡 Profile: {url}")
    driver.get(url)
    time.sleep(5)
    
    unique_tweets = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    scroll_attempts = 0
    max_scrolls = 20 # Captures ~100+ tweets per user if needed
    
    while scroll_attempts < max_scrolls:
        # Collect current rendered articles
        articles = driver.find_elements(By.TAG_NAME, "article")
        
        older_limit_hit = False
        
        for art in articles:
            try:
                # 1. Capture Time
                time_el = art.find_element(By.TAG_NAME, "time")
                ts_str = time_el.get_attribute("datetime")
                ts_dt = pd.to_datetime(ts_str).to_pydatetime()
                
                is_pinned = "Pinned" in art.text

                # 2. Capture Text (Data-Testid matches the content block)
                txt_el = art.find_element(By.CSS_SELECTOR, "div[data-testid='tweetText']")
                content = txt_el.text
                
                # Deduplication Key
                t_id = f"{ts_str}_{content[:25]}"
                
                if t_id not in unique_tweets:
                    if ts_dt >= cutoff:
                        unique_tweets[t_id] = {
                            "timestamp": ts_str,
                            "handle": f"@{handle}",
                            "content": content.replace("\n", " ") # Clean for AI readability
                        }
                    elif not is_pinned:
                        # Non-pinned tweet older than 7 days: safe to terminate
                        older_limit_hit = True
            except:
                continue

        if older_limit_hit:
            print(f"   ✓ Reached {cutoff.date()} (Historical Limit)")
            break

        # Scroll incrementally
        print(f"   ...scrolling (found {len(unique_tweets)})")
        driver.execute_script("window.scrollBy(0, 1500);")
        time.sleep(4) # Respect server response time
        scroll_attempts += 1
            
    return list(unique_tweets.values())

def main():
    args = get_args()
    
    # Automation Configuration
    headless = not args.visible
    fetch_replies = not args.no_replies # Logic: replies are default TRUE unless --no-replies is passed
    
    driver = setup_driver(headless=headless)
    
    try:
        # Step 1: Securely login using proven cookies
        if not inject_cookies(driver):
            return

        final_manifest = {}
        for handle in HANDLES:
            try:
                activity = scrape_handle(driver, handle, args.days, fetch_replies=fetch_replies)
                final_manifest[handle] = activity
                print(f"   ✅ Gathered {len(activity)} total updates.")
                time.sleep(5) # Cooldown between handles
            except Exception as e:
                print(f"   ⚠️ Could not scrape {handle}: {e}")

        # Step 2: Storage Preparation
        timestamp = datetime.now().strftime('%Y%m%d')
        output_payload = json.dumps(final_manifest, indent=2)
        
        # Step 3: Local Backup & S3 Archive
        with open(f"social_cache.json", "w") as f:
            f.write(output_payload)

        s3 = boto3.client('s3')
        s3_key = f"social/social_intel_{timestamp}.json"
        
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=output_payload,
            ContentType='application/json'
        )
        print(f"\n🚀 BIOSTACK AGENT: Social data stored at s3://{BUCKET_NAME}/{s3_key}")

    except Exception as fatal:
        print(f"❌ Script Fatality: {fatal}")
        driver.save_screenshot("fatal_error.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()