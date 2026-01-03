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
HANDLES = [h.strip() for h in os.getenv('X_FOLLOW_LIST', '').split(',')]

def setup_driver(headless=False):
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Fingerprint hiding
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def inject_cookies(driver):
    cookie_file = 'twitter_cookies.json'
    if not os.path.exists(cookie_file):
        raise Exception(f"❌ {cookie_file} not found! Export them from Chrome first.")
    
    # 1. We MUST visit the domain first to set context
    print("🌐 Opening X to establish context...")
    driver.get("https://x.com")
    time.sleep(3)

    # 2. Load and Inject
    with open(cookie_file, 'r') as f:
        cookies = json.load(f)
        
    print(f"🍪 Injecting {len(cookies)} cookies...")
    for cookie in cookies:
        # X cookies sometimes have 'expiry' or other keys Selenium dislikes
        # We strip non-standard keys to prevent errors
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
            pass # Skip incompatible cookies
            
    print("🔄 Refreshing to apply session...")
    driver.refresh()
    time.sleep(5)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=1)
    parser.add_argument('--visible', action='store_true')
    args = parser.parse_args()

    # If visible, we can watch it happen. If on AWS, headless.
    driver = setup_driver(headless=not args.visible)
    
    try:
        inject_cookies(driver)
        
        # 🧪 Check if we actually made it to the home feed
        if "login" in driver.current_url:
            print("❌ Injection FAILED. You are still on the login screen. Try re-exporting cookies.")
            return

        print("🚀 Injection SUCCESS. Starting scraping...")
        
        all_tweets = {}
        for handle in HANDLES:
            print(f"📡 Profile: @{handle}")
            driver.get(f"https://x.com/{handle}")
            time.sleep(7) # Critical for network render
            
            data = []
            articles = driver.find_elements(By.TAG_NAME, "article")
            cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
            
            for art in articles[:10]:
                try:
                    time_el = art.find_element(By.TAG_NAME, "time")
                    dt_str = time_el.get_attribute("datetime")
                    dt_obj = pd.to_datetime(dt_str).to_pydatetime()
                    
                    if dt_obj >= cutoff:
                        text_el = art.find_element(By.CSS_SELECTOR, "div[data-testid='tweetText']")
                        data.append({"time": dt_str, "content": text_el.text})
                except: continue
            
            all_tweets[handle] = data
            print(f"   found {len(data)}")

        # S3
        s3 = boto3.client('s3')
        ts = datetime.now().strftime('%Y%m%d')
        key = f"social/social_intel_{ts}.json"
        s3.put_object(Bucket=BUCKET_NAME, Key=key, Body=json.dumps(all_tweets))
        print(f"\n✅ DATA UPLOADED: {key}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()