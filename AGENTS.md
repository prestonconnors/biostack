---

### 2. AGENTS.md
*Create a file named `AGENTS.md` and paste this code.*

```markdown
# 🤖 Agent Context: BioStack

## Mission
This codebase represents an automated Personal Health Data Lake pipeline. The goal is to gather biometrics, perform pre-computation, and prepare highly optimized context for LLM analysis.

## Core Architecture Stack
*   **Language:** Python 3 (Scripts), Bash (Orchestration).
*   **Infrastructure:** AWS EC2 (Runtime), AWS S3 (Storage - JSON Lake).
*   **Auth Strategy:** Headless OAuth2 refresh flows (tokens generated locally, deployed to server).
*   **Dependencies:** `boto3`, `selenium`, `pandas`, `google-api-python-client`, `requests`.

## Data Dictionary & Constraints

### 1. Whoop Gatherer (`biostack_whoop.py`)
*   **Source:** Whoop API V2.
*   **Endpoints:** `cycles`, `recovery`, `sleep`, `workout`.
*   **Logic:** Uses specific "offline" scope to allow infinite refresh tokens. Catches 401 errors and auto-refreshes.
*   **Pagination:** Implements `nextToken` loop logic (Limit 25 items per page) to prevent data loss.
*   **Output:** Aggregated V2 Master Dictionary stored in S3.

### 2. Nutrition Gatherer (`biostack_nutrition.py`)
*   **Source:** MyNetDiary (No Public API).
*   **Method:** Selenium Web Scraper (Headless Chrome).
*   **Logic:**
    1.  Log in to Web Dashboard.
    2.  Hit hidden API endpoint: `exportData.do?year=YYYY`.
    3.  Download XLS file.
    4.  Use `pandas` to slice date range (Memory efficient).
*   **Constraint:** Requires `xlrd` library for older Excel formats. Server requires `--no-sandbox` flags.

### 3. Vitals Gatherer (`biostack_vitals.py`)
*   **Source:** Google Sheets API.
*   **Data Model:** Manual logs (Blood Pressure, Weight, SMM, Temp).
*   **Logic:** Simple Read-Only range fetch. Filters dates in Python.

### 4. The Analyst (`biostack_analyst.py`)
*   **Role:** Pre-processor (Compute over Token generation).
*   **Input:** Latest JSON dumps from S3 (Whoop, Nutrition, Vitals).
*   **Transformation Logic:**
    1.  **Normalization:** Converts mixed V1/V2 Whoop responses into Flat tables.
    2.  **Aggregation:** Pivots Raw Nutrition Logs (40+ rows/day) into Daily Totals (Calories, Macros).
    3.  **Tagging:** Wraps data in XML-style `<data name="x">` tags for robust LLM parsing.
    4.  **Format:** Output is Minified JSON inside the prompt to maximize token efficiency/speed (~1 minute thinking time).

### 5. Delivery (`biostack_drive.py`)
*   **Destination:** Google Drive API.
*   **Naming:** Dynamic date-stamped filename: `BioStack_Brief_YYYY-MM-DD_to_YYYY-MM-DD.txt`.
*   **Logic:** Checks for duplicates before upload. Uses distinct `drive_token.json`.

## Deployment Rules (If writing code)
1.  **Relative Paths:** All scripts MUST use `os.getcwd()` or dynamic path detection in Bash. Do not hardcode `/home/user`.
2.  **Environment Variables:** All Credentials MUST reside in `.env`.
3.  **Headless-First:** Any browser interaction MUST include `headless=new` options commented/uncommented for Debug/Prod toggling.
4.  **Date Handling:** All Dates sent to S3 should be Strings (ISO format) to avoid serialization errors.