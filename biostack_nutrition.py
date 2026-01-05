import os
import time
import glob
import json
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
from selenium.common.exceptions import TimeoutException

load_dotenv()

# --- CONFIG ---
MND_USER = os.getenv('MYNETDIARY_USER')
MND_PASS = os.getenv('MYNETDIARY_PASS')
BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, 'temp_downloads')

def get_args():
    parser = argparse.ArgumentParser(description="Fetch MyNetDiary Data")
    
    # Priority 1: Specific Dates
    parser.add_argument('--start', type=str, help='Start Date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End Date YYYY-MM-DD')
    
    # Priority 2: Relative Days (Default = 7)
    parser.add_argument('--days', type=int, default=7, help='Days back to fetch (default: 7)')
    
    return parser.parse_args()

def calculate_date_range(args):
    """ Returns (start_date_obj, end_date_obj) based on CLI args """
    if args.end:
        end_date = datetime.strptime(args.end, '%Y-%m-%d')
    else:
        end_date = datetime.now()

    if args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
    else:
        # Default to X days back from End Date
        start_date = end_date - timedelta(days=args.days)
    
    # Clean time to midnight
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    return start_date, end_date

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-east-1' 
    )

def setup_driver():
    # Cleanup previous downloads
    if os.path.exists(DOWNLOAD_DIR):
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
            try: os.remove(f)
            except: pass
    else:
        os.makedirs(DOWNLOAD_DIR)

    chrome_options = Options()
    
    # --- SERVER SETTINGS ---
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def safe_send_keys_with_wait(driver, possible_selectors, text):
    wait = WebDriverWait(driver, 10) 
    for selector in possible_selectors:
        try:
            elem = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            elem.clear()
            elem.send_keys(text)
            return True
        except:
            continue
    return False

def get_downloaded_files():
    """Returns list of valid completed download files in the temp dir."""
    files = glob.glob(os.path.join(DOWNLOAD_DIR, "*.*"))
    return [f for f in files if not f.endswith('.crdownload') and ('csv' in f.lower() or 'xls' in f.lower())]

def download_mynetdiary_years(target_years):
    """
    Downloads export files for multiple years in a SINGLE Selenium session.
    """
    driver = setup_driver()
    downloaded_paths = []
    
    try:
        # 1. Login
        login_url = "https://www.mynetdiary.com/logonPage.do"
        print(f"🤖 Logging in...")
        driver.get(login_url)
        
        if not safe_send_keys_with_wait(driver, ["#username-or-email", "input[name='j_username']"], MND_USER):
            raise Exception("Username field not found")
        if not safe_send_keys_with_wait(driver, ["#password", "input[name='j_password']"], MND_PASS):
            raise Exception("Password field not found")
        
        # Submit
        try:
            from selenium.webdriver.common.keys import Keys
            driver.find_element(By.CSS_SELECTOR, "input[type='password']").send_keys(Keys.RETURN)
        except:
            driver.find_element(By.CSS_SELECTOR, "button.btn-login").click()

        time.sleep(5) 

        # 2. Iterate through requested years
        for i, year in enumerate(target_years):
            expected_file_count = i + 1
            export_url = f"https://www.mynetdiary.com/exportData.do?year={year}"
            print(f"🚀 Triggering URL for Year {year}: {export_url}")
            driver.get(export_url)

            # 3. Wait for download to increment file count
            print(f"⏳ Waiting for Year {year} download...")
            start_time = time.time()
            success = False
            
            while time.time() - start_time < 60: 
                valid_files = get_downloaded_files()
                if len(valid_files) >= expected_file_count:
                    success = True
                    break
                time.sleep(1)
            
            if not success:
                print(f"⚠️ Warning: Timeout waiting for year {year}. It might not have data.")
        
        downloaded_paths = get_downloaded_files()
        if not downloaded_paths:
            raise Exception("No files were successfully downloaded.")
            
        return downloaded_paths

    finally:
        driver.quit()

def process_and_upload(csv_paths, start_date, end_date):
    print(f"⚙️  Processing {len(csv_paths)} file(s)... Filtering for {start_date.date()} to {end_date.date()}")
    
    all_dfs = []
    
    # 1. Load ALL files
    for csv_path in csv_paths:
        try:
            try:
                temp_df = pd.read_excel(csv_path)
            except:
                try:
                    temp_df = pd.read_csv(csv_path, sep='\t')
                except:
                    temp_df = pd.read_csv(csv_path)
            
            all_dfs.append(temp_df)
        except Exception as e:
            print(f"❌ Error reading file {csv_path}: {e}")
    
    if not all_dfs:
        print("❌ No dataframes could be loaded.")
        return

    try:
        # 2. Merge into one Master DataFrame
        df = pd.concat(all_dfs, ignore_index=True)

        # ⚠️ CRITICAL: Filter Data by Date
        # Ensure we find the date column. Usually 'Date'.
        date_col = None
        for col in df.columns:
            if 'date' in col.lower():
                date_col = col
                break
        
        if date_col:
            # Convert column to datetime objects
            df[date_col] = pd.to_datetime(df[date_col], dayfirst=False, errors='coerce')
            
            # Filter rows across all combined years
            mask = (df[date_col] >= start_date) & (df[date_col] <= end_date)
            df = df.loc[mask]
        else:
            print("⚠️ WARNING: Could not auto-detect a Date column. Uploading merged unfiltered file.")

        if df.empty:
            print("⚠️ No data matches that specific date range after filtering.")
            return

        # Prepare for Upload
        # Sort just in case merging messed up order
        if date_col:
            df = df.sort_values(by=date_col)
            
        data = df.fillna("").to_dict(orient='records')
        
        s3 = get_s3_client()
        timestamp_start = start_date.strftime('%Y%m%d')
        timestamp_end = end_date.strftime('%Y%m%d')
        key = f"nutrition/nutrition_{timestamp_start}_to_{timestamp_end}.json"
        
        print(f"🚀 Uploading {len(data)} merged records to S3...")
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(data, default=str),
            ContentType='application/json'
        )
        print(f"✅ SUCCESS: s3://{BUCKET_NAME}/{key}")
        
    except Exception as e:
        print(f"❌ Processing Error: {e}")
    finally:
        # cleanup
        for f in csv_paths:
            if os.path.exists(f):
                os.remove(f)

if __name__ == "__main__":
    args = get_args()
    start_date, end_date = calculate_date_range(args)
    
    # Identify unique years involved (e.g., 2025 and 2026)
    target_years = sorted(list(set(range(start_date.year, end_date.year + 1))))
    
    print(f"📅 Requested Range: {start_date.date()} -> {end_date.date()}")
    print(f"📂 Required Years: {target_years}")

    file_paths = download_mynetdiary_years(target_years)
    if file_paths:
        process_and_upload(file_paths, start_date, end_date)