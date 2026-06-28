import os
import re
import glob
import json
import boto3
import argparse
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
# MyNetDiary login credentials. Keep these in .env, not in git.
MND_USER = os.getenv("MYNETDIARY_USER")
MND_PASS = os.getenv("MYNETDIARY_PASS")
MND_REMEMBER_ME = os.getenv("MYNETDIARY_REMEMBER_ME", "true").lower() in {"1", "true", "yes", "y"}

BUCKET_NAME = os.getenv("BIOSTACK_BUCKET_NAME")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, "temp_downloads")

MYNETDIARY_BASE_URL = "https://www.mynetdiary.com"
MYNETDIARY_LOGIN_PAGE_URL = f"{MYNETDIARY_BASE_URL}/logonPage.do"
MYNETDIARY_LOGIN_DATA_URL = f"{MYNETDIARY_BASE_URL}/muiGetLoginPageData.do"
MYNETDIARY_SIGNIN_URL = f"{MYNETDIARY_BASE_URL}/muiSignIn.do"
MYNETDIARY_DASHBOARD_URL = f"{MYNETDIARY_BASE_URL}/dashboard.do"
MYNETDIARY_EXPORT_REFERER = f"{MYNETDIARY_BASE_URL}/analysisNavigator.do?selectedItem=dataExport"


class MyNetDiaryAuthError(RuntimeError):
    pass


def get_args():
    parser = argparse.ArgumentParser(description="Fetch MyNetDiary Data")

    # Priority 1: Specific Dates
    parser.add_argument("--start", type=str, help="Start Date YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="End Date YYYY-MM-DD")

    # Priority 2: Relative Days (Default = 7)
    parser.add_argument("--days", type=int, default=7, help="Days back to fetch (default: 7)")

    return parser.parse_args()


def calculate_date_range(args):
    """Returns (start_date_obj, end_date_obj) based on CLI args."""
    if args.end:
        end_date = datetime.strptime(args.end, "%Y-%m-%d")
    else:
        end_date = datetime.now()

    if args.start:
        start_date = datetime.strptime(args.start, "%Y-%m-%d")
    else:
        # Default to X days back from End Date
        start_date = end_date - timedelta(days=args.days)

    # Clean time to midnight
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    return start_date, end_date


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name="us-east-1",
    )


def clean_download_dir():
    """Remove old temporary MyNetDiary exports before each run."""
    if os.path.exists(DOWNLOAD_DIR):
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
            try:
                os.remove(f)
            except OSError:
                pass
    else:
        os.makedirs(DOWNLOAD_DIR)


def sanitize_filename(filename):
    """Keep filenames safe for local temp storage."""
    filename = filename.strip().strip('"').strip("'")
    filename = os.path.basename(filename)
    filename = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename)
    return filename or "mynetdiary_export"


def filename_from_content_disposition(content_disposition):
    """Extract filename= from Content-Disposition, if MyNetDiary provides it."""
    if not content_disposition:
        return None

    # Handles: filename="export.xls"
    match = re.search(r'filename="?([^";]+)"?', content_disposition, flags=re.IGNORECASE)
    if match:
        return sanitize_filename(match.group(1))

    # Handles: filename*=UTF-8''export.xls
    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, flags=re.IGNORECASE)
    if match:
        return sanitize_filename(match.group(1))

    return None


def extension_from_response(response):
    """Pick a reasonable extension when Content-Disposition has no filename."""
    content_type = response.headers.get("content-type", "").lower()

    if "spreadsheet" in content_type or "excel" in content_type or "ms-excel" in content_type:
        return ".xls"
    if "csv" in content_type:
        return ".csv"
    if "tab-separated" in content_type or "tsv" in content_type:
        return ".tsv"

    # MyNetDiary may return an Excel-compatible HTML/table export.
    return ".xls"


def build_browser_headers():
    """Reasonable browser-like default headers for requests.Session."""
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
    }


def make_mynetdiary_session():
    """
    Log in to MyNetDiary without Chrome/Selenium.

    The current web app login flow posts JSON to /muiSignIn.do:
      {"login": ..., "password": ..., "rememberMe": ...}

    On success, the response contains loggedIn=true and a JSESSIONID value.
    The browser JS sets document.cookie = "JSESSIONID=<value>" manually, so the
    requests.Session has to set that cookie manually too.
    """
    if not MND_USER or not MND_PASS:
        raise MyNetDiaryAuthError(
            "Missing MYNETDIARY_USER or MYNETDIARY_PASS in .env."
        )

    session = requests.Session()
    session.headers.update(build_browser_headers())

    # Some MyNetDiary requests include partnerId=0. It is harmless to seed it.
    session.cookies.set("partnerId", "0", domain="www.mynetdiary.com", path="/")

    print("🤖 Opening MyNetDiary login page...")
    login_page = session.get(MYNETDIARY_LOGIN_PAGE_URL, timeout=60)
    login_page.raise_for_status()

    # This mirrors the React app's page-data request. Login often works without it,
    # but keeping it here helps establish the same cookie/session context as the UI.
    try:
        session.get(
            MYNETDIARY_LOGIN_DATA_URL,
            params={
                "facebookError": "false",
                "googleError": "false",
                "appleError": "false",
                "profSignIn": "false",
            },
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": MYNETDIARY_LOGIN_PAGE_URL,
            },
            timeout=60,
        ).raise_for_status()
    except requests.RequestException as e:
        print(f"⚠️ Login page-data request failed, continuing anyway: {e}")

    print("🔐 Signing in to MyNetDiary...")
    response = session.post(
        MYNETDIARY_SIGNIN_URL,
        json={
            "login": MND_USER,
            "password": MND_PASS,
            "rememberMe": MND_REMEMBER_ME,
        },
        headers={
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": MYNETDIARY_BASE_URL,
            "Referer": MYNETDIARY_LOGIN_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=60,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as e:
        preview = response.text[:500].replace("\n", " ")
        raise MyNetDiaryAuthError(
            f"MyNetDiary login did not return JSON. Preview: {preview}"
        ) from e

    if not payload.get("loggedIn"):
        if payload.get("tryGoogle"):
            raise MyNetDiaryAuthError(
                "MyNetDiary says this account needs Google sign-in. "
                "This direct username/password flow will not work for that account."
            )
        raise MyNetDiaryAuthError(
            "MyNetDiary login failed. Check MYNETDIARY_USER and MYNETDIARY_PASS."
        )

    # Important: the React app sets JSESSIONID from the JSON response, not just Set-Cookie.
    jsessionid = payload.get("JSESSIONID")
    if jsessionid:
        session.cookies.set("JSESSIONID", jsessionid, domain="www.mynetdiary.com", path="/")
    else:
        # If the backend changes to Set-Cookie only, requests.Session may still have it.
        jsessionid = session.cookies.get("JSESSIONID")

    if not jsessionid:
        raise MyNetDiaryAuthError(
            "Login said loggedIn=true, but no JSESSIONID was returned or stored."
        )

    remember_me = payload.get("rememberMe")
    if remember_me:
        session.cookies.set("rememberMe", str(remember_me), domain="www.mynetdiary.com", path="/")

    redirect_url = payload.get("redirectUrl") or "/dashboard.do"
    if redirect_url.startswith("/"):
        redirect_url = f"{MYNETDIARY_BASE_URL}{redirect_url}"

    dashboard = session.get(
        redirect_url,
        headers={"Referer": MYNETDIARY_LOGIN_PAGE_URL},
        timeout=60,
    )
    dashboard.raise_for_status()

    if looks_like_login_page(dashboard):
        raise MyNetDiaryAuthError(
            "Login appeared to succeed, but dashboard still looks like a login page."
        )

    print("✅ MyNetDiary login succeeded.")
    return session


def looks_like_login_page(response):
    """Detect when MyNetDiary served a login page instead of the requested file/page."""
    final_url = response.url.lower()
    preview = response.content[:6000].decode("utf-8", errors="ignore").lower()

    login_markers = [
        "logonpage.do",
        "username-or-email",
        "email or account name",
        "invalid login or password",
        "you need to use sign in with google",
        "muiSignIn.do".lower(),
    ]

    return "logonpage.do" in final_url or any(marker in preview for marker in login_markers)


def assert_export_response_looks_valid(response, year):
    """Fail fast when the saved file is actually a login/error HTML page."""
    response.raise_for_status()

    if not response.content:
        raise RuntimeError(f"MyNetDiary returned an empty export for year {year}.")

    if looks_like_login_page(response):
        raise MyNetDiaryAuthError(
            f"MyNetDiary returned a login page for year {year}. "
            "The login session did not carry over to exportData.do."
        )

    preview = response.content[:4000].decode("utf-8", errors="ignore").lower()
    error_markers = ["an error occurred", "webserver encountered an internal error"]
    if any(marker in preview for marker in error_markers):
        raise RuntimeError(f"MyNetDiary returned an error page for year {year}.")


def download_mynetdiary_years(target_years):
    """Downloads export files for multiple years using direct HTTP requests."""
    clean_download_dir()
    downloaded_paths = []

    session = make_mynetdiary_session()

    for year in target_years:
        export_url = f"{MYNETDIARY_BASE_URL}/exportData.do"
        params = {"year": str(year)}

        print(f"🚀 Downloading MyNetDiary export for Year {year}...")
        response = session.get(
            export_url,
            params=params,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": MYNETDIARY_EXPORT_REFERER,
            },
            timeout=60,
        )
        assert_export_response_looks_valid(response, year)

        filename = filename_from_content_disposition(response.headers.get("content-disposition"))
        if not filename:
            filename = f"mynetdiary_export_{year}{extension_from_response(response)}"

        # Add the year if MyNetDiary reuses the same filename for multiple exports.
        stem, ext = os.path.splitext(filename)
        if str(year) not in stem:
            filename = f"{stem}_{year}{ext}"

        output_path = os.path.join(DOWNLOAD_DIR, filename)
        with open(output_path, "wb") as f:
            f.write(response.content)

        print(f"✅ Saved Year {year} export: {output_path}")
        downloaded_paths.append(output_path)

    if not downloaded_paths:
        raise RuntimeError("No files were successfully downloaded.")

    return downloaded_paths


def process_and_upload(csv_paths, start_date, end_date):
    print(f"⚙️  Processing {len(csv_paths)} file(s)... Filtering for {start_date.date()} to {end_date.date()}")

    all_dfs = []

    # 1. Load ALL files
    for csv_path in csv_paths:
        try:
            try:
                temp_df = pd.read_excel(csv_path)
            except Exception:
                try:
                    temp_df = pd.read_csv(csv_path, sep="\t")
                except Exception:
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
            if "date" in col.lower():
                date_col = col
                break

        if date_col:
            # Convert column to datetime objects
            df[date_col] = pd.to_datetime(df[date_col], dayfirst=False, errors="coerce")

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

        data = df.fillna("").to_dict(orient="records")

        s3 = get_s3_client()
        timestamp_start = start_date.strftime("%Y%m%d")
        timestamp_end = end_date.strftime("%Y%m%d")
        key = f"nutrition/nutrition_{timestamp_start}_to_{timestamp_end}.json"

        print(f"🚀 Uploading {len(data)} merged records to S3...")
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=json.dumps(data, default=str),
            ContentType="application/json",
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
