# BioStack 🧬

**BioStack** is an automated ETL (Extract, Transform, Load) pipeline for personal health data. It aggregates metrics from disconnected "walled gardens" (Whoop, MyNetDiary, Manual Google Sheets), normalizes the data into a private AWS S3 Data Lake, and pre-processes it for high-speed analysis by Large Language Models (LLMs).

## 🚀 The Architecture

The system consists of **Gatherers**, **Storage**, **Analysis**, and **Delivery**.

1.  **Gatherers**: Independent Python scripts fetch raw data from APIs or Web Scraping.
2.  **Storage**: Raw JSON data is stored in **AWS S3** (Private Data Lake).
3.  **The Analyst**: A logic engine that pulls specific date ranges from S3, "flattens" complex JSON (e.g., nested Whoop scores), calculates daily nutritional aggregates (Calories/Macros), and generates a token-optimized AI Prompt.
4.  **Delivery**: The final context-rich prompt is uploaded to **Google Drive** with a dynamic date range, ready for insertion into ChatGPT or Gemini.

## 📂 Repository Structure

```text
├── biostack_whoop.py      # OAuth2 Fetcher for Whoop V2 API (Recovery/Sleep/Strain)
├── biostack_nutrition.py  # Selenium Robot: Scrapes MyNetDiary export via headless Chrome
├── biostack_vitals.py     # API Reader for Manual Google Sheet Logs (BP, Weight, Body Comp)
├── biostack_analyst.py    # The Brain: Aggregates S3 data -> Optimized Prompt generation
├── biostack_drive.py      # The Courier: Uploads result to Google Drive (with Date Stamp)
├── run_all.sh             # Master orchestrator script (Auto-detects paths/env)
├── requirements.txt       # Python dependencies
└── .env.example           # Configuration template (rename to .env)
```

## 🛠 Prerequisites

*   **Python 3.10+**
*   **Google Chrome** (System-level installation required for the Selenium scraper).
*   **AWS S3 Bucket** (Private, IAM user with R/W access).
*   **API Credentials**:
    *   Whoop Developer App (Offline Scope).
    *   Google Cloud Project (Sheets API & Drive API enabled).
    *   MyNetDiary Account (Email/Password).

## ⚡ Installation & Setup

### 1. Local Setup (First Run)
*Note: You must run this on a computer with a screen (Local) first to generate the OAuth2 token files via browser interaction.*

1.  Clone repo and set up environment:
    ```bash
    git clone https://github.com/yourusername/biostack.git
    cd biostack
    python -m venv venv
    
    # Windows
    venv\Scripts\activate
    # Mac/Linux
    source venv/bin/activate
    
    pip install -r requirements.txt
    ```

2.  Configure Environment:
    *   Duplicate `.env.example` and rename it to `.env`.
    *   Fill in keys for AWS, Whoop, and Google Cloud.

3.  **Generate Tokens:**
    Run the following commands manually to handle the "Pop-up Browser" login flow.
    ```bash
    python biostack_whoop.py   # Generates whoop_tokens.json
    python biostack_vitals.py  # Generates google_token.json (for Sheets)
    python biostack_drive.py   # Generates drive_token.json (for Drive)
    ```

### 2. Server Deployment (AWS/Linux)
*Once tokens are generated locally, the system runs in "Headless" mode on a server.*

1.  Pull code to your server.
2.  Install Chrome for Linux (Debian/Ubuntu example):
    ```bash
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt install ./google-chrome-stable_current_amd64.deb -y
    ```
3.  **Critical Step:** Securely copy (SCP) your `.env` file and the 3 generated `*.json` token files from your local machine to the server directory.
4.  Make the shell script executable: 
    ```bash
    chmod +x run_all.sh
    ```

## 🤖 Usage

### Manual Trigger
Run the full suite (fetches the last 8 days by default to ensure full weekly coverage):
```bash
./run_all.sh
```

### Automation (Cron)
The `run_all.sh` script automatically detects its own location, making Cron setup easy.
Add this to `crontab -e` to run every Monday at 5:00 AM:

```bash
# Edit your path as necessary
0 5 * * 1 /home/ubuntu/biostack/run_all.sh >> /home/ubuntu/biostack/last_run.log 2>&1
```

## 📊 The "BioStack Prompt"
The output file (`biostack_prompt.txt`) uploaded to Drive contains **Minified JSON** XML blocks.
*   **Why?** JSON is faster for AI models to parse than Markdown tables.
*   **Speed:** Reduces AI "thinking time" from ~7 minutes to ~1 minute.
*   **Format:**
    ```xml
    <data name='nutrition_daily_totals'>[{"day": "2025-01-01", "calories": 2400...}]</data>
    ```

## 🔒 Security Note
*   **NEVER** commit `.env` or `*.json` token files to GitHub.
*   The included `.gitignore` is pre-configured to exclude these secrets.
*   AWS IAM User permissions should be restricted to **S3 Read/Write** only.

## 📄 License
Personal Use.