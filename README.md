# BioStack 🧬

**BioStack** is an automated ETL pipeline for personal health data. It aggregates metrics from disconnected sources such as Whoop, MyNetDiary, manual vitals logs, and expert social intel; normalizes the data into a private AWS S3 data lake; and pre-processes it for high-speed analysis by Large Language Models.

## 🚀 Architecture

1. **Gatherers**: Independent Python scripts fetch raw data from APIs and specialized collectors.
2. **Expert Intel**: Scans high-signal X accounts such as Bryan Johnson and Huberman Lab using the official **X API v2**. The social collector uses Bearer Token auth, Recent Search, and `since_id` caching to keep API usage cost-effective.
3. **Smart Nutrition**: The MyNetDiary scraper is Selenium-based and supports cross-year fetching. It detects ranges spanning year boundaries, downloads multiple export files in one session, and merges them into a unified dataset.
4. **Storage**: Raw and normalized JSON data is stored in a private AWS S3 data lake.
5. **The Analyst**: Pulls S3 data, flattens datasets, aggregates nutrition and biometrics, and correlates expert protocols against user data. Analyst JSON output is Pandas 4-friendly: numeric columns are rounded selectively, and datetimes are serialized as ISO strings.
6. **Delivery**: Uploads a token-optimized BioStack Brief to Google Drive for LLM review.

## 📂 Repository Structure

```text
├── biostack_whoop.py      # OAuth2 fetcher for Whoop API data
├── biostack_social.py     # Official X API v2 collector for expert social intel
├── biostack_nutrition.py  # Selenium scraper for MyNetDiary with multi-year merge support
├── biostack_vitals.py     # API reader for manual Google Sheet logs such as BP/weight
├── biostack_analyst.py    # S3 data -> compact analysis brief
├── biostack_drive.py      # Uploads generated brief to Google Drive
├── run_all.sh             # Master orchestrator script
├── templates/             # Analyst prompt templates
│   ├── default_coach.txt  # Standard evidence-based health prompt
│   └── preston_coach.txt  # Customized persona with specific health context
├── social_cache.json      # Local X API since_id cache; ignored by git
└── .env                   # Local secrets and config; ignored by git
```

## 🛠 Prerequisites

* **Python 3.10+** recommended.
* **AWS S3 bucket** with IAM read/write access.
* **Google Chrome** required only for the Nutrition scraper (`biostack_nutrition.py`). Social intel no longer requires Chrome.
* **X Developer Project/App** with active API access and a Bearer Token.

Install dependencies:

```bash
pip install requests boto3 pandas python-dotenv selenium webdriver-manager
```

Or, if your repo has `requirements.txt`:

```bash
pip install -r requirements.txt
```

## ⚡ Installation & Setup

### 1. Configure `.env`

Create `.env` from your example file or edit it directly:

```bash
cp .env.example .env
nano .env
```

Minimum social-intel config:

```bash
BIOSTACK_BUCKET_NAME=biostack-data-lake
X_FOLLOW_LIST=bryan_johnson,hubermanlab
X_BEARER_TOKEN=your_project_attached_x_api_bearer_token
```

Optional social cost controls:

```bash
BIOSTACK_SOCIAL_CACHE_KEY=social/social_cache.json
BIOSTACK_SOCIAL_OUTPUT_PREFIX=social
X_MAX_RESULTS=10
X_MAX_PAGES=1
```

### 2. Verify X API access

Your Bearer Token must come from a developer App attached to an X Project with active API access.

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

If you see `client-not-enrolled`, fix the Project/App/API-access enrollment in the X Developer Console and regenerate the Bearer Token.

### 3. Verify the social collector

```bash
python biostack_social.py --days 7 --debug
```

Successful output uploads daily social intel to:

```text
s3://<BIOSTACK_BUCKET_NAME>/social/social_intel_YYYYMMDD.json
```

It also writes a cache to:

```text
s3://<BIOSTACK_BUCKET_NAME>/social/social_cache.json
```

The date in the S3 filename uses UTC.

## 🖥 Usage

### Standard full run

Fetches the default range and uses the default coach template:

```bash
./run_all.sh
```

### Custom analyst template

```bash
./run_all.sh --template templates/preston_coach.txt
```

### Deep dive / longer date range

```bash
./run_all.sh --days 30
```

### Workflow retries

Each gather, analysis, and delivery step is attempted up to three times. Failed
steps wait 30 seconds before the second attempt and 60 seconds before the third.
The pipeline continues after a recovered step and stops if a step exhausts all
attempts.

Override the attempt count and initial delay with environment variables:

```bash
BIOSTACK_RETRY_ATTEMPTS=5 BIOSTACK_RETRY_DELAY_SECONDS=60 ./run_all.sh
```

Set `BIOSTACK_RETRY_ATTEMPTS=1` to disable retries. The delay doubles after each
failed attempt.

Nutrition handles year-end ranges automatically. X Recent Search supports only the recent window exposed by the X API, so the social collector is optimized for frequent small pulls rather than large historical backfills.

## 🧠 Social Intel Cost Controls

The official X API version of `biostack_social.py` is designed to avoid returning the same posts repeatedly.

Default production command:

```bash
python biostack_social.py --days 7 --max-results 10 --max-pages 1
```

Behavior:

* Uses `from:<handle> -is:retweet -is:reply` by default.
* Returns at most 10 posts per handle per page by default.
* Uses `since_id` after the first run so subsequent runs only fetch newer posts.
* Stores cache locally in `social_cache.json` and remotely at `social/social_cache.json` in S3.
* Merges multiple runs into the same daily S3 file without overwriting earlier posts.
* Builds the analyst's requested date window from all matching daily S3 files,
  deduplicating and filtering posts by their own timestamps.

The cache stores IDs and collection state to minimize X API reads; post bodies
are retained in the daily `social_intel_YYYYMMDD.json` objects. For example, a
`--days 28` workflow reuses the available 28-day S3 history while the collector
queries X only for recent posts that are not already represented by its cached
`since_id`.

For a fuller first backfill, run once with a higher page cap:

```bash
rm -f social_cache.json
aws s3 rm s3://biostack-data-lake/social/social_cache.json
python biostack_social.py --days 7 --max-results 10 --max-pages 3 --debug
```

Then return to the cheaper production command.

## 🤖 Resource Management on Small VMs

The pipeline is optimized for small AWS instances:

* **Social Intel**: Uses lightweight official X API requests. No Chrome, no Twikit, no X cookies, no password login.
* **Nutrition**: Uses Selenium with image blocking and atomic sessions to stay within memory limits.
* **S3 Cache**: Social state is preserved across cron runs and machines to reduce duplicate API reads.

## 📊 Automation: Cron

Run the full suite every Monday morning for a weekly trend brief:

```bash
0 5 * * 1 /home/ubuntu/biostack/run_all.sh --template templates/preston_coach.txt >> /home/ubuntu/biostack/run.log 2>&1
```

Run only the social collector:

```bash
0 */6 * * * cd /home/ubuntu/biostack && source venv/bin/activate && python biostack_social.py --days 7 --max-results 10 --max-pages 1 >> /home/ubuntu/biostack/social.log 2>&1
```

## 🔒 Security Notes

Keep these files out of git:

```gitignore
.env
social_cache.json
twitter_cookies.json
*_token.json
```

`twitter_cookies.json` is deprecated for social intel, but it should still be ignored if it exists from older Twikit-based runs.

## 🧯 Troubleshooting

### Pandas datetime JSON warnings from the analyst

If you see warnings like `obj.round has no effect with datetime` or `default 'epoch' date format is deprecated`, use the current `biostack_analyst.py`. Its compact JSON serializer rounds only numeric columns and explicitly writes datetime values with `date_format='iso'`.

## 📄 License

Personal Use. Developed for BioHackers.
