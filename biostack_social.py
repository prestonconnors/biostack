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

def get_args():
    parser = argparse.ArgumentParser(description="BioStack Expert Social Gatherer")
    parser.add_argument('--days', type=int, default=7, help="How many days back to look")
    parser.add_argument('--visible', action='store_true', help="Show the browser (laptop/debug mode)")
    parser.add_argument('--debug', action='store_true', help="Print every tweet timestamp/text as captured")
    return parser.parse_args()

def setup_driver(headless=True):
    chrome_options = Options()
    
    # --- PERFORMANCE: Image/Flash/CSS Blocking ---
    # 2 = Block, 1 = Allow
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1024,768") 

    # --- STEALTH ---
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Hide automation flag from X servers
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def inject_cookies(driver):
    cookie_path = 'twitter_cookies.json'
    if not os.path.exists(cookie_path):
        print("❌ twitter_cookies.json not found.")
        return False
    
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
    return "login" not in driver.current_url

def wipe_ui_elements(driver):
    """ AWS Optimization: Removes sidebars and clutter to save RAM """
    eraser_js = """
    const items = ['div[data-testid="sidebarColumn"]', 'nav[role="navigation"]', 'header[role="banner"]'];
    items.forEach(s => { let el = document.querySelector(s); if(el) el.remove(); });
    let main = document.querySelector('div[data-testid="primaryColumn"]');
    if(main) { main.style.maxWidth = '100%'; main.style.width = '100%'; }
    """
    try: driver.execute_script(eraser_js)
    except: pass

def scrape_handle(driver, handle, days, debug=False):
    url = f"https://x.com/{handle}/with_replies"
    print(f"📡 High-Efficiency Fetch: @{handle}")
    driver.get(url)
    
    time.sleep(6)
    wipe_ui_elements(driver)
    
    unique_tweets = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Small VM safe-scrolling
    for scroll in range(25):
        articles = driver.find_elements(By.TAG_NAME, "article")
        stop_scanning = False
        
        for art in articles:
            try:
                # Get Data
                time_el = art.find_element(By.TAG_NAME, "time")
                dt_str = time_el.get_attribute("datetime")
                dt_obj = pd.to_datetime(dt_str).to_pydatetime()
                
                txt_el = art.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                text = txt_el.text
                
                # Check Uniqueness
                t_id = f"{dt_str}_{text[:25]}"
                if t_id not in unique_tweets:
                    if dt_obj >= cutoff:
                        # Success Capture
                        unique_tweets[t_id] = {"ts": dt_str, "content": text.replace("\n", " ")}
                        
                        # DEBUG PRINTING
                        if debug:
                            print(f"   [DATA] {dt_obj.strftime('%m-%d %H:%M')} | {text[:75]}...")
                    
                    elif "Pinned" not in art.text:
                        # Boundary reached
                        stop_scanning = True
            except: 
                continue

        if stop_scanning: 
            print(f"   ✓ Time limit reached: {cutoff.date()}")
            break
        
        # Increment Scroll
        driver.execute_script("window.scrollBy(0, 1600);")
        time.sleep(2)
        if scroll % 5 == 0: wipe_ui_elements(driver)

    return list(unique_tweets.values())

def main():
    args = get_args()
    driver = setup_driver(headless=not args.visible)
    
    try:
        print("🔗 Establishing X session via Cookie Injection...")
        if not inject_cookies(driver):
            print("❌ Injection FAILED. Ensure your JSON cookies are current.")
            return
        
        master_intel = {}
        for h in HANDLES:
            try:
                intel = scrape_handle(driver, h, args.days, debug=args.debug)
                master_intel[h] = intel
                print(f"   ✅ Total items: {len(intel)}")
            except Exception as e:
                print(f"   ⚠️ Could not capture {h}: {e}")
            time.sleep(3)

        # ARCHIVE TO S3
        timestamp = datetime.now().strftime('%Y%m%d')
        key = f"social/social_intel_{timestamp}.json"
        
        s3 = boto3.client('s3')
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(master_intel, indent=2),
            ContentType='application/json'
        )
        print(f"\n🚀 ANALYSIS ASSETS STORED: {key}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()