# BioStack 🧬

**BioStack** is an automated ETL pipeline for personal health data. It pulls data from disconnected health and behavior platforms, normalizes it into a private AWS S3 data lake, and prepares token-efficient summaries for analysis by LLMs.

## 🚀 Architecture

1. **Gatherers**: Independent Python scripts fetch raw data from Whoop, MyNetDiary, Google Sheets, and selected expert social feeds.
2. **Expert Intel**: `biostack_social.py` scans high-signal X/Twitter activity using `twikit`, avoiding Chrome/Selenium browser scraping.
3. **Smart Nutrition**: `biostack_nutrition.py` logs in to MyNetDiary with `requests`, downloads yearly exports directly, supports cross-year date ranges, merges the exports, filters by date, and uploads normalized JSON to S3.
4. **Storage**: Raw and processed JSON data is stored in a private AWS S3 bucket.
5. **Analyst**: `biostack_analyst.py` pulls S3 data, flattens datasets, aggregates nutrition, and correlates expert protocols against biometrics.
6. **Delivery**: `biostack_drive.py` uploads a token-optimized BioStack Brief to Google Drive.

## 📂 Repository Structure

```text
├── biostack_whoop.py      # OAuth2 fetcher for Whoop API
├── biostack_social.py     # Twikit/API fetcher for expert X/Twitter activity
├── biostack_nutrition.py  # Requests-based MyNetDiary export fetcher
├── biostack_vitals.py     # Google Sheets reader for manual BP/weight logs
├── biostack_analyst.py    # S3 data -> token-optimized BioStack Brief
├── biostack_drive.py      # Uploads generated brief to Google Drive
├── run_all.sh             # Master orchestrator script
├── templates/             # Analyst prompt templates
│   ├── default_coach.txt
│   └── preston_coach.txt
├── twitter_cookies.json   # X/Twitter session cookies, user-supplied/private
└── .env                   # Secrets and credentials, never commit
```

## 🛠 Prerequisites

- Python 3.10+ recommended.
- AWS S3 bucket with read/write access.
- Google OAuth credentials/tokens for Whoop/Drive/Sheets flows where applicable.
- No Chrome, ChromeDriver, Selenium, or copied MyNetDiary browser cookie is required for the current nutrition flow.

Install dependencies:

```bash
pip install -r requirements.txt
```

If installing manually, the common dependencies are:

```bash
pip install requests twikit boto3 pandas python-dotenv xlrd openpyxl
```

## ⚡ Installation & Setup

### 1. Configure environment

Copy the example environment file, then fill in secrets:

```bash
cp .env.example .env
nano .env
```

Recommended `.env` values:

```bash
AWS_ACCESS_KEY_ID='...'
AWS_SECRET_ACCESS_KEY='...'
BIOSTACK_BUCKET_NAME='biostack-data-lake'

MYNETDIARY_USER='your_mynetdiary_login'
MYNETDIARY_PASS='your_mynetdiary_password'
MYNETDIARY_REMEMBER_ME=true

TWITTER_USERNAME='...'
TWITTER_EMAIL='...'
TWITTER_PASSWORD='...'
```

### 2. Authenticate services

Whoop:

```bash
python biostack_whoop.py
```

X/Twitter social collector:

1. Log in to X in your regular browser.
2. Export cookies as JSON.
3. Save them as `twitter_cookies.json` in the project root.
4. Add X credentials to `.env` so the social scraper can self-heal if cookies expire.

Test social collection:

```bash
python biostack_social.py --days 1 --debug
```

### 3. Test MyNetDiary nutrition export

Run a small date range first:

```bash
python biostack_nutrition.py --start 2026-06-01 --end 2026-06-27
```

Expected flow:

```text
Opening MyNetDiary login page...
Signing in to MyNetDiary...
MyNetDiary login succeeded.
Downloading MyNetDiary export for Year YYYY...
Processing file(s)...
SUCCESS: s3://...
```

## 🖥 Usage

### Standard run

Fetches the default recent window and uses the default coach template:

```bash
./run_all.sh
```

### Custom template

```bash
./run_all.sh --template templates/preston_coach.txt
```

### Date range / deep dive

```bash
./run_all.sh --days 30
```

For nutrition directly:

```bash
python biostack_nutrition.py --days 7
python biostack_nutrition.py --start 2026-06-01 --end 2026-06-27
```

The nutrition script automatically determines which years are needed, downloads one export per year, merges them, and filters the final dataset to the requested date range.

## 🤖 Resource Management

The pipeline is optimized for small AWS EC2 instances such as `t2.micro` or `t3.micro`.

- **Social Intel:** Direct API-style calls through `twikit`, no Chrome.
- **Nutrition:** Direct HTTP login/export through `requests`, no Chrome/Selenium.
- **Storage:** Compact JSON uploads to S3.
- **Failure Mode:** Scripts should fail clearly when credentials expire, login fails, exports are unavailable, or no rows match the requested date range.

## 📊 Automation with cron

Example weekly run every Monday at 5:00 AM:

```cron
0 5 * * 1 cd /home/ubuntu/biostack && /home/ubuntu/biostack/run_all.sh --template templates/preston_coach.txt >> /home/ubuntu/biostack/run.log 2>&1
```

Example daily nutrition refresh at 6:00 AM:

```cron
0 6 * * * cd /home/preston/biostack && /home/preston/biostack/venv/bin/python3 biostack_nutrition.py --days 7 >> /home/preston/biostack/logs/nutrition.log 2>&1
```

Create logs directory first:

```bash
mkdir -p /home/preston/biostack/logs
```

## 🔒 Security Notes

Never commit secrets, tokens, cookies, exports, or temporary downloads.

Recommended `.gitignore` entries:

```gitignore
.env
twitter_cookies.json
*_token.json
temp_downloads/
logs/
*.xls
*.xlsx
```

`twitter_cookies.json` contains an active X/Twitter session. MyNetDiary uses username/password login at runtime, so a copied MyNetDiary browser cookie is no longer needed.

## 📄 License

Personal use. Developed for BioHackers.
