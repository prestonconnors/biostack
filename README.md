# BioStack 🧬

**BioStack** is an automated ETL (Extract, Transform, Load) pipeline for personal health data. It aggregates metrics from disconnected "walled gardens" (Whoop, MyNetDiary, Expert Social Intel), normalizes the data into a private AWS S3 Data Lake, and pre-processes it for high-speed analysis by Large Language Models (LLMs).

## 🚀 The Architecture

1.  **Gatherers**: Independent Python scripts fetch raw data from APIs (Whoop, Sheets) and specialized collectors.
2.  **Expert Intel**: Specifically scans high-signal X (Twitter) feeds (Huberman, Attia, Johnson). Now utilizes an **API-based library (`twikit`)** for 10x faster collection and significantly lower CPU/RAM usage compared to legacy browser scraping.
3.  **Smart Nutrition**: The MyNetDiary scraper (Selenium-based) allows **Cross-Year Fetching**—it automatically detects date ranges spanning year boundaries (e.g., Dec '25 to Jan '26), downloads multiple export files in a single session, and merges them into a unified dataset.
4.  **Storage**: Raw JSON data is stored in **AWS S3** (Private Data Lake).
5.  **The Analyst**: Logic engine pulls S3 data, flattens datasets, aggregates nutrition, and correlates expert protocols against your biometrics (e.g., Does this new Huberman protocol explain my RHR spike?).
6.  **Delivery**: A token-optimized "BioStack Brief" is uploaded to **Google Drive**, ready for insert into your favorite LLM.

## 📂 Repository Structure

```text
├── biostack_whoop.py      # OAuth2 Fetcher for Whoop V2 API
├── biostack_social.py     # Twikit/API Fetcher: Expert Twitter activity (No Chrome required)
├── biostack_nutrition.py  # Selenium Scraper: MyNetDiary (Multi-year merge support)
├── biostack_vitals.py     # API Reader for Manual Google Sheet Logs (BP/Weight)
├── biostack_analyst.py    # The Brain: S3 Data -> XML/JSON Minified Prompt
├── biostack_drive.py      # The Courier: Uploads result to Google Drive
├── run_all.sh             # Master orchestrator script (CLI arguments supported)
├── templates/             # Folder containing Analyst Prompt Templates
│   ├── default_coach.txt  # Standard evidence-based health prompt
│   └── preston_coach.txt  # Customized persona with specific health history
├── twitter_cookies.json   # Exported Session Cookies (User-supplied)
└── .env                   # Keys (AWS, Google, MyNetDiary, X Credentials)
```

## 🛠 Prerequisites

*   **Google Chrome**: Required **ONLY** for the Nutrition scraper (`biostack_nutrition.py`).
*   **Python Libraries**: `pip install twikit boto3 pandas python-dotenv selenium webdriver-manager`.
*   **AWS S3 Bucket**: Private bucket with IAM R/W access.

## ⚡ Installation & Setup

### 1. Laptop Configuration (Initial Setup)
1.  **Install dependencies:** `pip install -r requirements.txt`.
2.  **Configure environment:** Duplicate `.env.example` to `.env`.
    *   Add `TWITTER_USERNAME`, `TWITTER_EMAIL`, and `TWITTER_PASSWORD` to allow the social scraper to self-heal if cookies expire.
3.  **Authentication:**
    *   Run `python biostack_whoop.py` (Local login for OAuth).
    *   Login to X on your regular browser, export cookies as **JSON** (using "EditThisCookie" extension), and save them as `twitter_cookies.json` in the project root.
4.  **Verification:** Test the social scraper locally:
    `python biostack_social.py --days 1 --debug`

### 2. Server Deployment (AWS EC2 / Linux)
1.  **Install Chrome binary** (For Nutrition Scraper):
    ```bash
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt install ./google-chrome-stable_current_amd64.deb -y
    ```
2.  **Sync secrets:** Securely copy (SCP) your `.env`, `twitter_cookies.json`, and any generated `*_token.json` files to the server.

## 🖥 Usage & Customization

The pipeline is controlled via `run_all.sh`. You can run it with default settings or customize the timeframe and the "Coach Persona" used for analysis.

### Standard Run
Fetches the last 7 days of data and uses the `default_coach.txt` template:
```bash
./run_all.sh
```

### Custom Template (Persona)
Switch the analysis logic to a specific user profile (e.g., specific medical history or goals) by pointing to a different text file in `templates/`:
```bash
./run_all.sh --template templates/preston_coach.txt
```

### Deep Dive / Date Range
Fetch more data for a monthly review. The scrapers automatically handle Year-End boundaries:
```bash
./run_all.sh --days 30
```

## 🤖 Resource Management (Small VMs)
The pipeline is optimized for **t2.micro (1GB RAM)** instances:
*   **Social Intel**: Now uses direct API calls via `twikit` (very low memory footprint).
*   **Nutrition**: Uses Selenium with image-blocking and atomic sessions to stay within memory limits.
*   **Self-Healing**: Scripts include logic to retry on network failures or API rate limits.

## 📊 Automation (Cron)
Run the full suite every Monday morning for a weekly trend brief:
```bash
0 5 * * 1 /home/ubuntu/biostack/run_all.sh --template templates/preston_coach.txt >> /home/ubuntu/biostack/run.log 2>&1
```

## 🔒 Security Note
The `twitter_cookies.json` file contains your active session. Keep this file private. The included `.gitignore` is pre-configured to ignore all token and cookie files.

## 📄 License
Personal Use. Developed for BioHackers.
```# BioStack 🧬

## 🚀 The Architecture

1.  **Gatherers**: Independent Python scripts fetch raw data from APIs (Whoop, Sheets) and specialized collectors.
2.  **Expert Intel**: Specifically scans high-signal X (Twitter) feeds. Now utilizes an **API-based library (`twikit`)** for 10x faster collection and significantly lower CPU/RAM usage compared to previous browser-based versions.
3.  **Smart Nutrition**: The MyNetDiary scraper (Selenium-based) allows **Cross-Year Fetching**...

## 📂 Repository Structure

```text
├── biostack_social.py     # Lightweight API-based fetcher for X (No longer requires Chrome)
├── biostack_nutrition.py  # Selenium Scraper: MyNetDiary (Requires Chrome)
...
├── twitter_cookies.json   # Exported Session Cookies
└── .env                   # Keys (AWS, Google, MyNetDiary, X Credentials)
🛠 Prerequisites

Google Chrome: Required ONLY for the Nutrition scraper (biostack_nutrition.py).

Python Libraries: pip install twikit boto3 pandas python-dotenv.

X Credentials: For the Social scraper, add TWITTER_USERNAME, TWITTER_EMAIL, and TWITTER_PASSWORD to your .env to allow the script to self-heal if cookies expire.

⚡ Installation & Setup
1. Authentication

Social Scraper:

Login to X on your regular browser.

Use an extension (e.g., EditThisCookie) to export cookies as JSON.

Save as twitter_cookies.json in the root folder.

Optional but Recommended: Add your X password to .env so the script can re-authenticate automatically if the server is logged out.

🤖 Resource Management

The pipeline is optimized for t2.micro (1GB RAM) instances:

Social: Now uses direct API calls (very low memory).

Nutrition: Uses Selenium with image-blocking and atomic sessions to stay within memory limits.

code
Code
download
content_copy
expand_less
### Key Changes Made:
1.  **Dependency Shift**: Noted that Chrome is no longer required for `biostack_social.py`.
2.  **Auth Update**: Added mention of `TWITTER_PASSWORD` in `.env` as a fallback mechanism.
3.  **Performance**: Highlighted the move from "Browser Scraping" to "Internal API" which is a major stability upgrade for small AWS instances.