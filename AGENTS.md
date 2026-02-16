# 🤖 Agent Context: BioStack (Updated)

## Mission
To maintain a high-integrity Personal Health Data Lake (PHDL) that correlates objective physiological data with external expert protocols.

## Core Architecture Stack
*   **Scraping Strategy:** 
    *   **Social:** Uses the `twikit` library to perform internal API requests, bypassing the high overhead of a headless browser.
    *   **Nutrition:** Selenium-driven collection for MyNetDiary (walled garden). Optimized for low-RAM AWS instances.
*   **Security & Persistence:** 
    *   **Session Proxying:** Uses `twitter_cookies.json` to maintain active sessions. Supports automated fallback to username/password login if cookies expire.

## Data Dictionary & Constraints

### 2. Social Expert Intel (`biostack_social.py`)
*   **Ingestion:** Fetches X (Twitter) timelines and replies via API simulation.
*   **Resource Management:** 
    *   **Zero-Browser Overhead:** Replaced Selenium with a request-based library, reducing RAM usage from ~500MB+ to <50MB per session.
    *   **Rate Limit Awareness:** Implements back-off timers and `TooManyRequests` handling to prevent account flagging.
    *   **Authentication:** Dual-layer auth. Prioritizes local JSON cookies; falls back to environment-stored credentials (`TWITTER_PASSWORD`) to auto-refresh expired sessions.

### 3. Nutrition & Vitals (`biostack_nutrition.py`)
*   **Smart Ingestion:** Features **Multi-Year Merge Logic**. Handles Dec–Jan transitions by iteratively downloading year-end exports and merging in-memory before S3 upload.
...