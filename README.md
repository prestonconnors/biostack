# BioStack 🧬

**BioStack** is an automated ETL (Extract, Transform, Load) pipeline for personal health data. It aggregates metrics from disconnected "walled gardens" (Whoop, MyNetDiary, Expert Social Intel), normalizes the data into a private AWS S3 Data Lake, and pre-processes it for high-speed analysis by Large Language Models (LLMs).

## 🚀 The Architecture

1.  **Gatherers**: Independent Python scripts fetch raw data from APIs (Whoop, Sheets) and high-performance Selenium Scrapers.
2.  **Expert Intel**: Specifically scans high-signal X (Twitter) feeds (Huberman, Attia, Johnson) for new health protocols using **Cookie Injection** and **Virtual Scrolling**.
3.  **Storage**: Raw JSON data is stored in **AWS S3** (Private Data Lake).
4.  **The Analyst**: Logic engine pulls S3 data, flattens datasets, aggregates nutrition, and correlates expert protocols against your biometrics (e.g., Does this new Huberman protocol explain my RHR spike?).
5.  **Delivery**: A token-optimized "BioStack Brief" is uploaded to **Google Drive**, ready for insert into your favorite LLM.

## 📂 Repository Structure

```text
├── biostack_whoop.py      # OAuth2 Fetcher for Whoop V2 API
├── biostack_social.py     # Selenium Scraper: Expert Twitter activity via Cookie Injection
├── biostack_nutrition.py  # Selenium Scraper: MyNetDiary logs via Headless Chrome
├── biostack_vitals.py     # API Reader for Manual Google Sheet Logs (BP/Weight)
├── biostack_analyst.py    # The Brain: S3 Data -> XML/JSON Minified Prompt
├── biostack_drive.py      # The Courier: Uploads result to Google Drive
├── run_all.sh             # Master orchestrator script
├── twitter_cookies.json   # Exported Session Cookies (User-supplied)
└── .env                   # Keys (AWS, Google, MyNetDiary, X handles)
```

## 🛠 Prerequisites

*   **Google Chrome**: Required for both Nutrition and Social Intel gatherers.
*   **AWS S3 Bucket**: Private bucket with IAM R/W access.
*   **Cookie Export Extension**: (e.g., `EditThisCookie`) Required on your local browser to generate the initial session for the Social Scraper.

## ⚡ Installation & Setup

### 1. Laptop Configuration (Initial Setup)
1.  **Install dependencies:** `pip install -r requirements.txt`.
2.  **Configure environment:** Duplicate `.env.example` to `.env` and add your keys/X handles.
3.  **Authentication:**
    *   Run `python biostack_whoop.py` (Local login for OAuth).
    *   Login to X on your regular browser, export cookies as **JSON**, and save them as `twitter_cookies.json` in the project root.
4.  **Verification:** Test the social scraper locally with visibility:
    `python biostack_social.py --days 1 --visible --debug`

### 2. Server Deployment (AWS EC2 / Linux)
1.  **Install Chrome binary:**
    ```bash
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt install ./google-chrome-stable_current_amd64.deb -y
    ```
2.  **Sync secrets:** Securely copy (SCP) your `.env`, `twitter_cookies.json`, and any generated `*_token.json` files to the server.

## 🤖 Resource Management (Small VMs)
`biostack_social.py` is purpose-built for low-RAM AWS instances (t2.micro/t3.small):
*   **Image Blocking**: Refuses to download images/video to save ~80% CPU/Bandwidth.
*   **Atomic Sessions**: Restarts a clean Chrome process per handle to prevent RAM leak crashes.
*   **Self-Healing**: Detects "Tab Crashes" (OOM errors) and automatically retries scraping.

## 📊 Automation (Cron)
Run the full suite every Monday morning for a weekly trend brief:
```bash
0 5 * * 1 /home/ubuntu/biostack/run_all.sh >> /home/ubuntu/biostack/run.log 2>&1
```

## 🔒 Security Note
The `twitter_cookies.json` file contains your active session. Keep this file private. The included `.gitignore` is pre-configured to ignore all token and cookie files.

## 📄 License
Personal Use. Developed for BioHackers.