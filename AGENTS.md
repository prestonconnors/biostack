# 🤖 Agent Context: BioStack

## Mission

Maintain a high-integrity Personal Health Data Lake (PHDL) that correlates objective physiological data, manually logged vitals, nutrition exports, and external expert protocols.

## Core Architecture Stack

### Scraping / Collection Strategy

- **Whoop:** OAuth/API-based fetcher.
- **Vitals:** API reader for manually maintained Google Sheet logs.
- **Social Expert Intel:** Uses `twikit` to perform API-style requests for X/Twitter activity without Chrome or Selenium.
- **Nutrition:** Uses a `requests.Session()` login flow for MyNetDiary, then downloads yearly exports directly from `exportData.do?year=YYYY`. No Chrome, ChromeDriver, Selenium, or manually copied session cookies are required.

### Storage & Delivery

- **Storage:** Private AWS S3 data lake.
- **Analysis:** `biostack_analyst.py` flattens and summarizes datasets into a token-optimized BioStack Brief.
- **Delivery:** `biostack_drive.py` uploads the resulting brief to Google Drive.

## Security & Persistence

- Keep all credentials and tokens out of git.
- `.env` stores secrets such as:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `BIOSTACK_BUCKET_NAME`
  - `MYNETDIARY_USER`
  - `MYNETDIARY_PASS`
  - `MYNETDIARY_REMEMBER_ME`
  - `TWITTER_USERNAME`
  - `TWITTER_EMAIL`
  - `TWITTER_PASSWORD`
- `twitter_cookies.json` may contain an active X/Twitter session and must remain private.
- MyNetDiary no longer relies on a copied browser cookie. The script authenticates directly with username/password and stores the returned session in memory for the current run.

## Data Dictionary & Constraints

### 1. Whoop (`biostack_whoop.py`)

- Fetches physiological metrics from the Whoop API.
- Uses OAuth token persistence through local token files.
- Token files must be ignored by git.

### 2. Social Expert Intel (`biostack_social.py`)

- Fetches selected high-signal X/Twitter timelines and replies via API simulation.
- Uses `twikit`, avoiding browser overhead.
- Handles rate limits with backoff timers and `TooManyRequests` handling.
- Authentication prioritizes local JSON cookies and can fall back to environment-stored credentials if configured.

### 3. Nutrition (`biostack_nutrition.py`)

- Logs in to MyNetDiary using a direct HTTP flow.
- Opens the login page to establish initial cookies, then posts credentials to the MyNetDiary sign-in endpoint.
- Downloads one export per required year from `exportData.do?year=YYYY`.
- Supports **Multi-Year Merge Logic** for date ranges crossing year boundaries, such as Dec–Jan.
- Merges yearly files in memory, filters rows to the requested date range, and uploads JSON to S3 under:

```text
nutrition/nutrition_YYYYMMDD_to_YYYYMMDD.json
```

### 4. Vitals (`biostack_vitals.py`)

- Reads manual logs such as blood pressure, weight, and related health markers from Google Sheets.
- Uploads normalized records to the data lake.

### 5. Analyst (`biostack_analyst.py`)

- Pulls S3 data, normalizes records, aggregates nutrition, and prepares LLM-ready summaries.
- Should avoid hallucinating medical conclusions. Flag correlations as hypotheses unless strongly supported by the data.

### 6. Drive Delivery (`biostack_drive.py`)

- Uploads the generated BioStack Brief to Google Drive for easy reuse.

## Resource Management

The pipeline is intended to run on small AWS EC2 instances such as `t2.micro` / `t3.micro`.

- **Social:** No Chrome. Low memory footprint through `twikit`.
- **Nutrition:** No Chrome. Direct HTTP login/export with `requests`.
- **S3 Uploads:** Keep outputs compact JSON.
- **Retries:** Prefer clean failure messages over silent partial uploads.

## Operational Notes

- Use `./run_all.sh` for standard orchestration.
- Use `--days`, `--start`, and `--end` for date range control when supported by the underlying scripts.
- Before committing, verify `.gitignore` covers:
  - `.env`
  - `twitter_cookies.json`
  - `*_token.json`
  - `temp_downloads/`
  - `logs/`
  - `*.xls`
  - `*.xlsx`
