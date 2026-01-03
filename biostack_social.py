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
    parser = argparse.ArgumentParser(description="BioStack Expert Social Gatherer")
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--visible', action='store_true')
    return parser.parse_args()

def setup_driver(headless=True):
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1280,1024") 
    
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def inject_cookies(driver):
    cookie_path = 'twitter_cookies.json'
    if not os.path.exists(cookie_path):
        raise Exception(f"❌ {cookie_path} missing! Export JSON cookies from Chrome first.")
    
    driver.get("https://x.com")
    time.sleep(2)
    with open(cookie_path, 'r') as f:
        cookies = json.load(f)
    for cookie in cookies:
        clean_cookie = {'name': cookie['name'], 'value': cookie['value'], 'domain': cookie['domain'], 'path': '/', 'secure': True}
        try: driver.add_cookie(clean_cookie)
        except: pass
    driver.get("https://x.com/home")
    time.sleep(4)
    return "login" not in driver.current_url

def optimize_page_for_vm(driver):
    """ JS Hack: Removes heavy UI elements to save CPU/RAM on small AWS VMs """
    js = """
    var sidebars = document.querySelectorAll('div[data-testid="sidebarColumn"], nav[role="navigation"], div[role="progressbar"]');
    sidebars.forEach(el => el.remove());
    var primaryColumn = document.querySelector('div[data-testid="primaryColumn"]');
    if (primaryColumn) { primaryColumn.style.maxWidth = '100%'; primaryColumn.style.width = '100%'; }
    """
    try: driver.execute_script(js)
    except: pass

def scrape_handle(driver, handle, days):
    url = f"https://x.com/{handle}/with_replies"
    print(f"📡 Profile Activity: @{handle} (Targeting {days} days)")
    driver.get(url)
    time.sleep(6)
    
    optimize_page_for_vm(driver)
    
    unique_tweets = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    # We scroll until we hit a tweet older than the cutoff
    # This ensures we get EVERYTHING but stop ASAP to save VM resources
    max_scrolls = 25 
    for i in range(max_scrolls):
        articles = driver.find_elements(By.TAG_NAME, "article")
        found_historical_boundary = False
        
        for art in articles:
            try:
                time_el = art.find_element(By.TAG_NAME, "time")
                ts_str = time_el.get_attribute("datetime")
                ts_dt = pd.to_datetime(ts_str).to_pydatetime()
                
                # Dedupe
                txt_el = art.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                content = txt_el.text
                t_id = f"{ts_str}_{content[:20]}"
                
                if t_id not in unique_tweets:
                    if ts_dt >= cutoff:
                        unique_tweets[t_id] = {"timestamp": ts_str, "content": content.replace("\n", " ")}
                    elif "Pinned" not in art.text:
                        # Found a regular tweet older than 7 days. We can stop scrolling.
                        found_historical_boundary = True
            except: continue

        if found_historical_boundary:
            print(f"   ✓ Historical limit reached ({cutoff.date()})")
            break
            
        # Perform incremental scroll
        print(f"   ...scrolling (found {len(unique_tweets)})")
        driver.execute_script("window.scrollBy(0, 1800);")
        time.sleep(3) # Let VM network catch up

    return list(unique_tweets.values())

def main():
    args = get_args()
    driver = setup_driver(headless=not args.visible)
    
    try:
        if not inject_cookies(driver):
            print("❌ Injection FAILED.")
            return

        final_manifest = {}
        for handle in HANDLES:
            try:
                data = scrape_handle(driver, handle, args.days)
                final_manifest[handle] = data
                print(f"   ✅ Total Activity for @{handle}: {len(data)} items")
                time.sleep(5)
            except Exception as e:
                print(f"   ⚠️ Error scraping @{handle}: {e}")

        # --- S3 SAVE ---
        ts = datetime.now().strftime('%Y%m%d')
        s3 = boto3.client('s3')
        s3_key = f"social/social_intel_{ts}.json"
        
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=json.dumps(final_manifest, indent=2),
            ContentType='application/json'
        )
        print(f"\n🚀 ANALYSIS PREPARED: s3://{BUCKET_NAME}/{s3_key}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()