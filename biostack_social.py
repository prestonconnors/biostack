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
from selenium.common.exceptions import WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
HANDLES = [h.strip() for h in os.getenv('X_FOLLOW_LIST', '').split(',') if h.strip()]

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--visible', action='store_true')
    parser.add_argument('--debug', action='store_true')
    return parser.parse_args()

def setup_driver(headless=True):
    chrome_options = Options()
    
    # PERFORMANCE & MEMORY (Hardened for AWS)
    prefs = {"profile.managed_default_content_settings.images": 2}
    chrome_options.add_experimental_option("prefs", prefs)

    if headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage") # Use /tmp instead of memory
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1280,720")
        # Resource constraints
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--memory-pressure-off")
    
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def inject_cookies(driver):
    cookie_path = 'twitter_cookies.json'
    if not os.path.exists(cookie_path): return False
    
    try:
        driver.get("https://x.com")
        time.sleep(3)
        with open(cookie_path, 'r') as f:
            cookies = json.load(f)
        for cookie in cookies:
            c = {'name': cookie['name'], 'value': cookie['value'], 'domain': cookie['domain'], 'path': '/'}
            try: driver.add_cookie(c)
            except: pass
        driver.get("https://x.com/home")
        time.sleep(4)
        return "login" not in driver.current_url
    except Exception as e:
        print(f"Cookie injection error: {e}")
        return False

def wipe_ui(driver):
    js = "const s = ['div[data-testid=\"sidebarColumn\"]', 'nav[role=\"navigation\"]', 'header[role=\"banner\"]']; s.forEach(x => { let e = document.querySelector(x); if(e) e.remove(); });"
    try: driver.execute_script(js)
    except: pass

def scrape_handle(driver, handle, days, debug=False):
    driver.get(f"https://x.com/{handle}/with_replies")
    time.sleep(6)
    wipe_ui(driver)
    
    unique_tweets = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    for scroll in range(20):
        try:
            articles = driver.find_elements(By.TAG_NAME, "article")
            stop_scan = False
            for art in articles:
                try:
                    time_el = art.find_element(By.TAG_NAME, "time")
                    ts = time_el.get_attribute("datetime")
                    dt_obj = pd.to_datetime(ts).to_pydatetime()
                    
                    text_el = art.find_element(By.CSS_SELECTOR, 'div[data-testid="tweetText"]')
                    content = text_el.text
                    
                    t_id = f"{ts}_{content[:20]}"
                    if t_id not in unique_tweets:
                        if dt_obj >= cutoff:
                            unique_tweets[t_id] = {"ts": ts, "content": content.replace("\n", " ")}
                            if debug: print(f"   [+] {dt_obj.strftime('%m-%d')} | {content[:60]}...")
                        elif "Pinned" not in art.text:
                            stop_scan = True
                except: continue
            
            if stop_scan: break
            driver.execute_script("window.scrollBy(0, 1500);")
            time.sleep(2.5) # Increased for stability
        except WebDriverException as we:
            raise we # Re-throw to handle crash in the main loop
            
    return list(unique_tweets.values())

def main():
    args = get_args()
    master_intel = {}
    
    for handle in HANDLES:
        success = False
        retries = 0
        
        while not success and retries < 2:
            print(f"📡 Processing @{handle} (Attempt {retries+1})...")
            driver = None
            try:
                driver = setup_driver(headless=not args.visible)
                if not inject_cookies(driver):
                    print(f"   ❌ Cookie fail on @{handle}")
                    break
                
                intel = scrape_handle(driver, handle, args.days, debug=args.debug)
                master_intel[handle] = intel
                print(f"   ✅ Done: {len(intel)} tweets.")
                success = True
                
            except WebDriverException as e:
                retries += 1
                print(f"   ⚠️ TAB CRASHED or Driver Failed. Retrying...")
                time.sleep(5)
            except Exception as fatal:
                print(f"   ❌ Unexpected Error on @{handle}: {fatal}")
                break
            finally:
                if driver: 
                    try: driver.quit()
                    except: pass
                # Forced pause to let OS reclaim RAM
                time.sleep(2)

    # UPLOAD
    if master_intel:
        key = f"social/social_intel_{datetime.now().strftime('%Y%m%d')}.json"
        boto3.client('s3').put_object(
            Bucket=BUCKET_NAME, Key=key, 
            Body=json.dumps(master_intel, indent=2)
        )
        print(f"🚀 SUCCESS: s3://{BUCKET_NAME}/{key}")

if __name__ == "__main__":
    main()