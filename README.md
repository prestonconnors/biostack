# BioStack 🧬

**BioStack** is an automated ETL (Extract, Transform, Load) pipeline for personal health data. It aggregates metrics from disconnected "walled gardens" (Whoop, MyNetDiary, Expert Social Feeds), normalizes the data into a private AWS S3 Data Lake, and pre-processes it for high-speed analysis by Large Language Models (LLMs).

## 🚀 The Architecture

The system consists of **Gatherers**, **Storage**, **Analysis**, and **Delivery**.

1.  **Gatherers**: Independent Python scripts fetch raw data. 
    *   **APIs**: Whoop V2, Google Sheets (Vitals).
    *   **Automation**: Selenium Robot scrapes MyNetDiary (Nutrition) and X.com (Expert Intel via Cookie Injection).
2.  **Storage**: Raw data is stored as date-stamped JSON in an **AWS S3** Private Data Lake.
3.  **The Analyst**: A logic engine pulls specific date ranges from S3, flattens complex nested metrics, calculates daily aggregates (Macros/Sleep), and matches Expert Social activity to your specific health data.
4.  **Delivery**: An optimized "Brief" (Minified JSON + Context) is uploaded to **Google Drive**, ready for instant AI analysis.

## 📂 Repository Structure

```text
├── biostack_whoop.py      # OAuth2 Fetcher for Whoop (Sleep/HRV/Strain)
├── biostack_nutrition.py  # Selenium Robot: Scrapes MyNetDiary daily logs
├── biostack_social.py     # Selenium Robot: Scrapes Expert Activity (Huberman/Johnson/Attia)
├── biostack_vitals.py     # API Reader for Manual Sheets Logs (BP/Body Comp)
├── biostack_analyst.py    # The Brain: Aggregates S3 data -> XML Prompt
├── biostack_drive.py      # The Courier: Uploads Brief to Google Drive
├── run_all.sh             # Master orchestrator script
├── twitter_cookies.json   # Exported Session (Required for Social gatherer)
├── requirements.txt       # Dependencies
└── .env                   # Keys (AWS, Google, MyNetDiary, X handles)
```

## 🛠 Prerequisites

*   **Python 3.10+**
*   **Google Chrome**: Required for headless scraping on both laptop and server.
*   **S3 Bucket**: Private bucket with IAM R/W access.
*   **Cookie Export**: You must export your Twitter session cookies as a JSON file (`twitter_cookies.json`) from your desktop browser (e.g., using 'EditThisCookie').

## ⚡ Installation & Setup

### 1. Laptop Configuration (Initial Setup)
1.  Clone repo and install deps:
    ```bash
    pip install -r requirements.txt
    ```
2.  Setup `.env`: Rename `.env.example` to `.env` and fill in your keys. Include `X_FOLLOW_LIST` handles (e.g., `hubermanlab,bryan_johnson`).
3.  **Cookies:** Login to Twitter/X in your normal Chrome browser. Export cookies to JSON and save as `twitter_cookies.json` in the project root.
4.  **Tokens:** Run gatherers manually to handle OAuth logins for Whoop and Google.

### 2. Server Deployment (AWS/Linux)
1.  Install Chrome for Linux:
    ```bash
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt install ./google-chrome-stable_current_amd64.deb -y
    ```
2.  **Migration:** Securely copy (SCP) your `.env`, `twitter_cookies.json`, and the generated `*.json` token files from your laptop to the server.
3.  Set execution permissions: `chmod +x run_all.sh`.

## 🤖 Usage

### Local Testing (Visible Mode)
To see the expert scraper working in real-time on your laptop:
```bash
python biostack_social.py --days 1 --visible
```

### Automation (Headless Mode)
Run the master suite (runs weekly coverage by default):
```bash
./run_all.sh
```

Add to `crontab -e` for weekly Monday 5:00 AM analysis:
```bash
0 5 * * 1 /home/ubuntu/biostack/run_all.sh >> /home/ubuntu/biostack/run.log 2>&1
```

## 🔒 Security Note
*   **Critical**: `twitter_cookies.json` contains your live auth session. Treat it as securely as your AWS secret keys.
*   AWS IAM permissions should be scoped exclusively to S3 **Read/Write** on the target bucket only.
*   All automated scraping scripts use a `user-agent` rotation to maintain account safety.

## 📄 License
Personal Health Data Framework. Free for personal use.