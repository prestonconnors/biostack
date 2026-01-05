Here is the updated `AGENTS.md` file.

I have updated the **The Analyst** section to reflect the new Persona/Template architecture and added a note about argument handling in the **Automation** section.

```markdown
# 🤖 Agent Context: BioStack

## Mission
To maintain a high-integrity Personal Health Data Lake (PHDL) that correlates objective physiological data with external expert protocols. This system transforms raw S3 data into high-density, XML-wrapped JSON payloads for LLM-driven wellness analysis, utilizing configurable "Coach Personas" to tailor advice.

## Core Architecture Stack
*   **Storage Strategy:** Private "JSON-Lake" on S3, organized by provider and timestamp.
*   **Scraping Strategy:** Selenium-driven collection for "walled gardens" without APIs. Optimized for headless execution on low-RAM AWS instances (t2.micro / t3.small).
*   **Security & Persistence:** 
    *   **OAuth2:** Managed refresh flows for persistent API access.
    *   **Session Proxying:** Uses **Cookie Injection** (transferring laptop Chrome cookies to the server) to bypass X/Twitter login security walls and API paywalls.

## Data Dictionary & Constraints

### 1. Whoop V2 (`biostack_whoop.py`)
*   Standard wearable ingestion. Flattens nested V2 structures (Stage Summaries, Recovery Scores) for token-efficient prompt delivery.

### 2. Social Expert Intel (`biostack_social.py`)
*   **Ingestion:** Scrapes X (Twitter) feeds including direct tweets and threaded replies (`/with_replies`).
*   **Resource Management (Hardened for AWS):**
    *   **Image/CSS Suppression:** Prevents download of non-text assets to save ~80% of CPU/RAM during browser render.
    *   **Atomic Browser Sessions:** Re-initializes a fresh Chrome process for every handle to prevent cumulative RAM leakage (memory-pressure prevention).
    *   **DOM Cleaning:** Uses JavaScript to physically remove high-load UI elements (sidebars, trending banners) after page load.
    *   **Self-Healing Logic:** Implements an automated restart/retry loop for "Tab Crashed" or OOM (Out of Memory) errors, resuming collection until successful.

### 3. Nutrition & Vitals
*   **Nutrition:** Downloads daily macro/calorie summaries via Selenium login flows.
*   **Vitals:** Ingests manual blood pressure and body composition logs from Google Sheets API.

### 4. The Analyst (`biostack_analyst.py`)
*   **Persona-Driven Logic:** Dynamically loads prompt templates (e.g., `preston_coach.txt` vs `default_coach.txt`) via CLI arguments (`--template`). This isolates medical history and goals from the code, allowing multiple users or changing strategies without refactoring.
*   **Data Minimization:** Sums nutritional events into daily macro-summaries to save LLM context window space.
*   **Protocol Contextualization:** Presents Expert Intel from the `social/` bucket alongside Biometric failings, allowing the LLM to verify protocol-fit (e.g., *Is this Bryan Johnson protocol actually addressing a spike in my RHR?*).

## Automation & Stability Rules
1.  **Zombie Cleanup:** All scrapers must use `try/finally` blocks to explicitly kill Chrome/Chromedriver processes to prevent OS-level memory starvation on 1GB RAM instances.
2.  **Stateless Injection:** Relies on local `twitter_cookies.json` being synced to the server root for auth-free landing.
3.  **Debug Integrity:** Supports `--debug` for real-time streaming of captured content to the console, allowing monitor-less debugging of AWS scrapers.
4.  **Date Awareness:** Uses strict UTC-anchored time comparison to deduplicate entries during "Virtual Scroll" captures.
5.  **Template Safety:** The Analyst checks for the `{{DATASET}}` token in custom templates and defaults to a fallback prompt if the template file is missing or malformed to ensure pipeline continuity.
```