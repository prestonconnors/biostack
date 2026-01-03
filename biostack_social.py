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
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
HANDLES = [h.strip() for h in os.getenv('X_FOLLOW_LIST', '').split(',') if h.strip()]

def setup_driver(headless=True):
    chrome_options = Options()
    
    # 1. DISABLE IMAGES (Saves massive CPU/RAM)
    # 1 = Allow, 2 = Block
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.stylesheets": 2, # Risky, but fast
    }
    chrome_options.add_experimental_option("prefs", prefs)

    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        # Smaller window = fewer elements to track in memory
        chrome_options.add_argument("--window-size=800,600") 

    # Mask automation
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def inject_cookies(driver):
    cookie_path = 'twitter_cookies.json'
    if not os.path.exists(cookie_path): return False
    
    driver.get("https://x.com")
    time.sleep(2)
    with open(cookie_path, 'r') as f:
        cookies = json.load(f)
    for cookie in cookies:
        c = {'name': cookie['name'], 'value': cookie['value'], 'domain': cookie['domain'], 'path': '/'}
        try: driver.add_cookie(c)
        except: pass
    driver.get("https://x.com/home")
    time.sleep(3)
    return True

def wipe_page_logic(driver):
    """ Deletes every UI element on X that isn't a Tweet Article """
    eraser_js = """
    const itemsToKill = [
        'div[data-testid="sidebarColumn"]',
        'nav[role="navigation"]',
        'header[role="banner"]',
        'div[data-testid="placementTracking"]',
        'div[aria-label="Relevant people"]',
        'div[aria-label="Who to follow"]'
    ];
    itemsToKill.forEach(sel => {
        let el = document.querySelector(sel);
        if(el) el.remove();
    });
    // Set content column to full width for easier finding
    let main = document.querySelector('div[data-testid="primaryColumn"]');
    if(main) { main.style.maxWidth = '100%'; main.style.width = '100%'; }
    """
    try: driver.execute_script(eraser_js)
    except: pass

def scrape_handle(driver, handle, days):
    url = f"https://x.com/{handle}/with_replies"
    print(f"📡 High-Efficiency Scrape: @{handle}")
    driver.get(url)
    
    # Wait for the timeline to actually appear
    time.sleep(5)
    wipe_page_logic(driver)
    
    unique_tweets = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Since we blocked images, scrolling is MUCH smoother and faster
    for scroll in range(20):
        # We search specifically for content blocks
        articles = driver.find_elements(By.TAG_NAME, "article")
        stop_now = False
        
        for art in articles:
            try:
                time_el = art.find_element(By.TAG_NAME, "time")
                dt_str = time_el.get_attribute("datetime")
                dt_obj = pd.to_datetime(dt_str).to_pydatetime()
                
                txt_el = art.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                text = txt_el.text
                
                # Deduplication key
                t_id = f"{dt_str}_{text[:20]}"
                
                if t_id not in unique_tweets:
                    if dt_obj >= cutoff:
                        unique_tweets[t_id] = {"ts": dt_str, "content": text.replace("\n", " ")}
                    elif "Pinned" not in art.text:
                        stop_now = True
            except: continue

        if stop_now: break
        
        # Incremental scroll - faster on VMs because images are missing
        driver.execute_script("window.scrollBy(0, 1500);")
        time.sleep(1.5) # Reduced from 3s to 1.5s
        
        # Periodic UI cleanup during long scrolls
        if scroll % 5 == 0: wipe_page_logic(driver)

    return list(unique_tweets.values())

def main():
    args = argparse.ArgumentParser()
    args.add_argument('--days', type=int, default=7)
    args.add_argument('--visible', action='store_true')
    opts = args.parse_args()

    driver = setup_driver(headless=not opts.visible)
    
    try:
        if not inject_cookies(driver): return
        
        final_out = {}
        for h in HANDLES:
            try:
                tweets = scrape_handle(driver, h, opts.days)
                final_out[h] = tweets
                print(f"   ✓ Captured {len(tweets)}")
            except Exception as e:
                print(f"   ⚠️ Error: {e}")

        # S3 Archive
        ts = datetime.now().strftime('%Y%m%d')
        boto3.client('s3').put_object(
            Bucket=BUCKET_NAME,
            Key=f"social/social_intel_{ts}.json",
            Body=json.dumps(final_out, indent=2)
        )
        print(f"🚀 FINISHED: Archiving to social/social_intel_{ts}.json")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()