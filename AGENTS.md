# 🤖 Agent Context: BioStack

## Mission
Maintain a high-integrity Personal Health Data Lake (PHDL) that correlates objective physiological data with external expert protocols and user biometrics.

## Core Architecture Stack

### Data Collection Strategy
* **Whoop:** OAuth2/API fetcher for recovery, strain, sleep, HR, and related physiological metrics.
* **Nutrition:** Selenium-driven MyNetDiary collection for the walled-garden nutrition export flow. Optimized for low-RAM AWS instances.
* **Vitals:** API-based reader for manually logged vitals in Google Sheets.
* **Social Expert Intel:** Official **X API v2** collector using Bearer Token auth and Recent Search queries. This replaced the prior Twikit/cookie-based scraper.

### Security & Persistence
* **Official X API Auth:** `biostack_social.py` uses `X_BEARER_TOKEN` from a developer App attached to an X Project with active API access.
* **No X Cookies / No Password Fallback:** Social ingestion no longer uses `twitter_cookies.json`, `TWITTER_USERNAME`, `TWITTER_EMAIL`, or `TWITTER_PASSWORD`.
* **S3 Cache:** Social ingestion maintains `social/social_cache.json` in S3 plus a local `social_cache.json` to persist per-handle `since_id` state and avoid paying to re-read the same posts.
* **Private Data Lake:** Raw and processed outputs are written to the configured private AWS S3 bucket.
* **Secrets:** `.env`, token files, cookies, and local caches must remain ignored by git.

## Data Dictionary & Constraints

### 1. Whoop (`biostack_whoop.py`)
* **Ingestion:** Pulls Whoop data through OAuth2/API.
* **Persistence:** Stores raw normalized data in S3 for downstream analysis.
* **Constraint:** Requires valid OAuth token lifecycle handling.

### 2. Social Expert Intel (`biostack_social.py`)
* **Ingestion:** Fetches recent public posts from high-signal X accounts using the official X API v2 Recent Search endpoint.
* **Query Pattern:** Uses `from:<handle>` plus `-is:retweet` and `-is:reply` by default to reduce noise and API cost.
* **Authentication:** Requires `X_BEARER_TOKEN` only. The token must come from an X developer App attached to a Project with active API access.
* **Cost Controls:**
  * Defaults to `--max-results 10` and `--max-pages 1` per handle.
  * Uses cached `since_id` per handle after the first run so repeat runs return only newer posts.
  * Uses S3 cache (`social/social_cache.json`) to keep state across machines and cron executions.
  * Supports `--force-full-scan`, but this can increase API spend.
* **Output:** Writes daily merged JSON to `s3://<BIOSTACK_BUCKET_NAME>/social/social_intel_YYYYMMDD.json` using UTC dates.
* **Important Constraint:** Do not reintroduce Twikit, username/password login, or browser-exported X cookies for this collector.

### 3. Nutrition & Vitals (`biostack_nutrition.py`, `biostack_vitals.py`)
* **Smart Ingestion:** Nutrition supports multi-year merge logic and handles Dec-Jan transitions by downloading year-end exports and merging in memory before S3 upload.
* **Resource Management:** Selenium is still required for MyNetDiary only; it should remain isolated from the social collector.
* **Vitals:** Reads manual health logs such as BP/weight from Google Sheets or configured API sources.

### 4. Analyst (`biostack_analyst.py`)
* **Purpose:** Pulls S3 data, flattens datasets, aggregates nutrition/vitals/whoop metrics, and correlates expert protocols against personal biometrics.
* **Output:** Produces token-optimized BioStack briefs for downstream LLM analysis.

### 5. Delivery (`biostack_drive.py`)
* **Purpose:** Uploads the generated BioStack Brief to Google Drive.

## Operational Defaults

### Social Collector Normal Run
```bash
python biostack_social.py --days 7 --max-results 10 --max-pages 1
```

### Social Collector First Backfill / Fuller Catch-Up
Use sparingly because it can return more paid resources:
```bash
python biostack_social.py --days 7 --max-results 10 --max-pages 3 --debug
```

### X API Verification
```bash
set -a
source .env
set +a

curl "https://api.x.com/2/users/by/username/xdevelopers" \
  -H "Authorization: Bearer $X_BEARER_TOKEN"
```

Expected success shape:
```json
{"data":{"id":"2244994945","name":"Developers","username":"XDevelopers"}}
```

## Environment Variables

Required for social ingestion:
```bash
BIOSTACK_BUCKET_NAME=biostack-data-lake
X_FOLLOW_LIST=bryan_johnson,hubermanlab
X_BEARER_TOKEN=your_project_attached_x_api_bearer_token
```

Optional social tuning:
```bash
BIOSTACK_SOCIAL_CACHE_KEY=social/social_cache.json
BIOSTACK_SOCIAL_OUTPUT_PREFIX=social
X_MAX_RESULTS=10
X_MAX_PAGES=1
```

Deprecated for social ingestion:
```bash
TWITTER_USERNAME=
TWITTER_EMAIL=
TWITTER_PASSWORD=
twitter_cookies.json
```

## Git Hygiene

Ensure these are ignored:
```gitignore
.env
social_cache.json
twitter_cookies.json
*_token.json
```
