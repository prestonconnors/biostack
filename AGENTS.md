# 🤖 Agent Context: BioStack

## Mission
This codebase represents an automated Personal Health Data Lake (PHDL) and Analyst. Its purpose is to ingest high-frequency biometrics (Wearables), low-frequency biometrics (Vitals/Lab), and behavior logs (Nutrition), while correlating them against high-signal expert protocols (Social Intel).

## Core Architecture Stack
*   **Storage:** AWS S3 Private "JSON-Lake." Data is tiered by type: `/whoop`, `/nutrition`, `/vitals`, and `/social`.
*   **Infrastructure:** Optimized for Linux Headless runtime (AWS EC2/Lambda) with a Local-Manual flow for 2FA-protected endpoints.
*   **Identity & Auth:** 
    *   **OAuth2:** Managed refresh flows (Whoop/Google Sheets/Drive).
    *   **Cookie Injection:** Session persistence via exported `twitter_cookies.json` to bypass X/Twitter login security blocks.

## Data Dictionary & Constraints

### 1. Whoop V2 (`biostack_whoop.py`)
*   **Model:** Fetcher for `cycles`, `recovery`, `sleep`, and `workout`.
*   **Logic:** Uses "offline" scope for infinite background token refresh. Implements V2 pagination logic via `nextToken`.

### 2. Social Intel (`biostack_social.py`)
*   **Source:** X/Twitter profiles via Selenium Scraper.
*   **Stealth:** Utilizes user-agent spoofing, cookie injection (bypassing the login paywall), and virtual-scrolling logic.
*   **Default Behavior:** Scrapes `/with_replies` by default to capture "gold nuggets" of expert interaction. 
*   **Filter:** Strictly date-filters tweets using a UTC `datetime` object to ignore irrelevant historical data.

### 3. Nutrition (`biostack_nutrition.py`)
*   **Method:** Scrapes the MyNetDiary "Export Data" CSV/XLS tool using Selenium.
*   **Cleanup:** Pandas filters the spreadsheet rows for the relevant date-range before JSON serialization.

### 4. Vitals (`biostack_vitals.py`)
*   **Model:** Reads Google Sheets logs for "Human-Input" metrics (Blood Pressure, Weight, SMM, Body Fat %).
*   **Auth:** Requires `credentials.json` (Service/App auth) and local-server flow on the first run.

### 5. The Analyst (`biostack_analyst.py`)
*   **The Pre-processor:** Not just an aggregator, but a data-shrinker. It minimizes token usage by flattening nested Whoop JSON and summing raw Nutrition logs into "Daily Aggregates."
*   **Correlative Signal:** Maps `Nutrition Day N` -> `Recovery Day N+1` to assist the LLM in finding sleep/performance friction.
*   **Dataset Wrapping:** Output is minified JSON wrapped in XML tags (`<data name="...">`) for robust parsing by LLMs.

### 6. Delivery (`biostack_drive.py`)
*   **Format:** Plain-text "BioStack Brief" (.txt) containing the LLM-optimized prompt context.
*   **Log Logic:** Uses dynamic date-stamp filenames: `BioStack_Brief_YYYY-MM-DD_to_YYYY-MM-DD.txt`.

## Deployment Rules for New Code
1.  **Headless Support:** All Selenium initializations must check for `--headless` and `--no-sandbox` to prevent crashes in CI/CD or Server environments.
2.  **Relative Paths:** No hardcoded paths. All tokens/secrets are referenced relative to the project root.
3.  **Error Resilience:** All scrapers must use `try/finally` blocks to ensure `driver.quit()` is called, preventing orphaned Chrome processes (zombie browsers) from exhausting Server RAM.
4.  **Date Handling:** All scrapers must adhere to the `datetime.now(timezone.utc)` standard for multi-source synchronization.