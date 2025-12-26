import os
import time
import glob
import json
import boto3
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException

# Load env variables (Ensure .env exists on your server!)
load_dotenv()

# --- CONFIG ---
MND_USER = os.getenv('MYNETDIARY_USER')
MND_PASS = os.getenv('MYNETDIARY_PASS')
BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')

# Ensure we use absolute paths for Linux stability
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, 'temp_downloads')

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-east-1' # Change if your bucket is elsewhere, helps stability
    )

def setup_driver():
    # clean up previous downloads first to avoid confusion
    if os.path.exists(DOWNLOAD_DIR):
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
            try:
                os.remove(f)
            except: pass
    else:
        os.makedirs(DOWNLOAD_DIR)

    chrome_options = Options()
    
    # --- LINUX SERVER SETTINGS (Active) ---
    chrome_options.add_argument("--headless=new")  # Invisible mode
    chrome_options.add_argument("--no-sandbox")    # Required for running as root/linux
    chrome_options.add_argument("--disable-dev-shm-usage") # Overcomes limited resource problems
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")

    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    # Automatically install/manage the correct Chrome Driver
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def safe_send_keys_with_wait(driver, possible_selectors, text):
    wait = WebDriverWait(driver, 10) # Increased wait time for server network lag
    for selector in possible_selectors:
        try:
            elem = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            elem.clear()
            elem.send_keys(text)
            print(f"   -> Filled field: {selector}")
            return True
        except TimeoutException:
            continue
        except Exception:
            pass
    return False

def download_mynetdiary_csv():
    driver = setup_driver()
    try:
        # 1. Login
        login_url = "https://www.mynetdiary.com/logonPage.do"
        print(f"🤖 [Server] Navigating to Login: {login_url}")
        driver.get(login_url)
        
        # User
        if not safe_send_keys_with_wait(driver, ["#username-or-email", "input[name='j_username']"], MND_USER):
            print(f"DEBUG: Source preview: {driver.page_source[:500]}")
            raise Exception("❌ Username field not found")
        
        # Pass
        if not safe_send_keys_with_wait(driver, ["#password", "input[name='j_password']"], MND_PASS):
            raise Exception("❌ Password field not found")
        
        # Submit
        try:
            from selenium.webdriver.common.keys import Keys
            driver.find_element(By.CSS_SELECTOR, "input[type='password']").send_keys(Keys.RETURN)
            print("   -> Sent Enter Key")
        except:
            driver.find_element(By.CSS_SELECTOR, "button.btn-login").click()

        time.sleep(5) 

        # 2. Trigger "Instant Download" URL
        current_year = datetime.now().year
        export_url = f"https://www.mynetdiary.com/exportData.do?year={current_year}"
        print(f"🚀 [Server] Triggering Download URL: {export_url}")
        
        driver.get(export_url)

        # 3. Wait for file
        print("⏳ [Server] Watching download folder...")
        start_time = time.time()
        while time.time() - start_time < 60: # 60s timeout for server
            files = glob.glob(os.path.join(DOWNLOAD_DIR, "*.*"))
            # Filter logic
            valid_files = [f for f in files if not f.endswith('.crdownload') and ('csv' in f.lower() or 'xls' in f.lower())]
            
            if valid_files:
                final_file = valid_files[0]
                print(f"✅ File Captured: {os.path.basename(final_file)}")
                return final_file
            time.sleep(1)
        
        raise Exception("❌ Download timed out. Page content dump: " + driver.title)

    finally:
        driver.quit()

def process_and_upload(csv_path):
    print("⚙️ Processing Data...")
    try:
        # Try strict Excel, then fallback
        try:
            df = pd.read_excel(csv_path)
        except Exception:
            try:
                # Sometimes it's a TSV disguised as XLS
                df = pd.read_csv(csv_path, sep='\t')
            except:
                df = pd.read_csv(csv_path)

        data = df.fillna("").to_dict(orient='records')
        
        s3 = get_s3_client()
        timestamp = datetime.now().strftime('%Y-%m-%d')
        key = f"nutrition/mynetdiary_raw_{timestamp}.json"
        
        print(f"🚀 Uploading {len(data)} records to AWS S3...")
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(data, default=str),
            ContentType='application/json'
        )
        print(f"✅ SUCCESS: s3://{BUCKET_NAME}/{key}")
        
        # Cleanup
        os.remove(csv_path)
    
    except Exception as e:
        print(f"❌ Processing Error: {e}")

if __name__ == "__main__":
    file_path = download_mynetdiary_csv()
    if file_path:
        process_and_upload(file_path)