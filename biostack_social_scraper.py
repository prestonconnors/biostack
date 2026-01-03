import os
import json
import time
import boto3
import argparse
import pandas as pd
from datetime import datetime, timedelta
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
X_USER = os.getenv('X_USER')
X_PASS = os.getenv('X_PASS')
BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
HANDLES = [h.strip() for h in os.getenv('X_FOLLOW_LIST', '').split(',') if h.strip()]

def setup_driver():
    chrome_options = Options()
    # REQUIRED FOR AWS
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # IMPORTANT: Spoofing the User Agent is required to avoid instant block
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def login_to_x(driver):
    wait = WebDriverWait(driver, 20)
    print("🔐 Opening Login Page...")
    driver.get("https://x.com/i/flow/login")
    
    # 1. Enter Username
    print("   Sending username...")
    user_field = wait.until(EC.presence_of_element_located((By.NAME, "text")))
    user_field.send_keys(X_USER)
    driver.find_element(By.XPATH, "//span[text()='Next']").click()
    
    # 2. Handle potential "Unusual Activity" (Enter Phone or Email Handle)
    time.sleep(3)
    try:
        # Check if it asks for user handle/phone again as a check
        check_field = driver.find_elements(By.CSS_SELECTOR, "data-testid='ocfEnterTextTextInput'")
        if check_field:
            print("⚠️ Unusual activity check triggered. Sending username again...")
            check_field[0].send_keys(X_USER) # Use your @handle or email here
            driver.find_element(By.XPATH, "//span[text()='Next']").click()
            time.sleep(2)
    except:
        pass

    # 3. Enter Password
    print("   Sending password...")
    pass_field = wait.until(EC.presence_of_element_located((By.NAME, "password")))
    pass_field.send_keys(X_PASS)
    driver.find_element(By.XPATH, "//span[text()='Log in']").click()
    
    # 4. HANDLE 2FA / EMAIL VERIFICATION (Manual Intervention Mode)
    # This will wait for the home screen OR prompt the AWS terminal if it sees a verification field
    time.sleep(5)
    if "login" in driver.current_url:
        print("\n🚫 Verification Code Required!")
        print("Twitter likely sent an email to your address.")
        v_code = input("PASTE CODE FROM EMAIL: ").strip()
        
        v_input = driver.find_element(By.NAME, "text") # Verification input name
        v_input.send_keys(v_code)
        driver.find_element(By.XPATH, "//span[text()='Next']").click()
        time.sleep(5)

    print("✅ Login Finalized.")

def scrape_handle(driver, handle, days):
    print(f"📡 Profile: @{handle}...")
    driver.get(f"https://x.com/{handle}")
    time.sleep(7) # Extra buffer for server network speed
    
    tweets_data = []
    articles = driver.find_elements(By.TAG_NAME, "article")
    
    cutoff = datetime.now() - timedelta(days=days)
    
    for article in articles[:10]:
        try:
            # 1. Date
            time_el = article.find_element(By.TAG_NAME, "time")
            dt_str = time_el.get_attribute("datetime")
            dt_obj = pd.to_datetime(dt_str).replace(tzinfo=None)
            
            if dt_obj > cutoff:
                # 2. Text
                text_el = article.find_element(By.CSS_SELECTOR, "div[data-testid='tweetText']")
                tweets_data.append({
                    "created_at": dt_str,
                    "text": text_el.text
                })
        except:
            continue
            
    return tweets_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=1)
    args = parser.parse_args()

    driver = setup_driver()
    try:
        login_to_x(driver)
        all_results = {}
        
        for h in HANDLES:
            tweets = scrape_handle(driver, h, args.days)
            all_results[h] = tweets
            print(f"   ✓ Captured {len(tweets)}")
            
        # S3 UPLOAD
        s3 = boto3.client('s3')
        ts = datetime.now().strftime('%Y%m%d')
        key = f"social/tweets_{ts}.json"
        
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(all_results),
            ContentType='application/json'
        )
        print(f"🚀 SAVED: {key}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()