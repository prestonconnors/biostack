#!/bin/bash

set -euo pipefail

# Resolve relative paths from this script's directory so the pipeline works
# regardless of the caller's current working directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ------------------------------------------------------------------
# BioStack Master Orchestrator 🧬
# 
# Usage: 
#   ./run_all.sh                        # Uses default template & 7 days
#   ./run_all.sh --template custom.txt  # Uses specific prompt template
#   ./run_all.sh --days 14              # Fetches 2 weeks of data
# ------------------------------------------------------------------

# 1. Set Defaults
TEMPLATE="$SCRIPT_DIR/templates/default_coach.txt"
DAYS=7
RETRY_ATTEMPTS="${BIOSTACK_RETRY_ATTEMPTS:-3}"
RETRY_DELAY_SECONDS="${BIOSTACK_RETRY_DELAY_SECONDS:-30}"

run_with_retry() {
    local step_name="$1"
    shift

    local attempt=1
    local delay="$RETRY_DELAY_SECONDS"
    local exit_code

    while true; do
        if "$@"; then
            if (( attempt > 1 )); then
                echo "✅ [$step_name] Recovered on attempt $attempt/$RETRY_ATTEMPTS."
            fi
            return 0
        else
            exit_code=$?
        fi

        if (( attempt >= RETRY_ATTEMPTS )); then
            echo "❌ [$step_name] Failed after $attempt attempt(s) (exit code $exit_code)." >&2
            return "$exit_code"
        fi

        echo "⚠️ [$step_name] Attempt $attempt/$RETRY_ATTEMPTS failed with exit code $exit_code. Retrying in ${delay}s..." >&2
        sleep "$delay"
        attempt=$((attempt + 1))
        delay=$((delay * 2))
    done
}

# 2. Parse Arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -t|--template) TEMPLATE="$2"; shift ;;
        -d|--days) DAYS="$2"; shift ;;
        *) echo "❌ Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if ! [[ "$RETRY_ATTEMPTS" =~ ^[1-9][0-9]*$ ]]; then
    echo "❌ BIOSTACK_RETRY_ATTEMPTS must be a positive integer." >&2
    exit 2
fi

if ! [[ "$RETRY_DELAY_SECONDS" =~ ^[0-9]+$ ]]; then
    echo "❌ BIOSTACK_RETRY_DELAY_SECONDS must be a non-negative integer." >&2
    exit 2
fi

# 3. Verify Template Exists
if [ ! -f "$TEMPLATE" ]; then
    echo "❌ Error: Template file not found at '$TEMPLATE'"
    echo "   Please check the path or create the file."
    exit 1
fi

echo "=========================================="
echo "🧬 BioStack Pipeline Initiated"
echo "📅 Time Window: Last $DAYS days"
echo "📄 Prompt Template: $TEMPLATE"
echo "=========================================="

# 4. Activate Virtual Env (Optional - Uncomment if using venv)
source "$SCRIPT_DIR/venv/bin/activate"

# 5. Execute Gatherers (Sequential execution to save RAM on small AWS instances)
echo ""
echo "1️⃣  [Gather] Whoop Wearable Data..."
run_with_retry "Whoop Gather" python biostack_whoop.py --days "$DAYS"

echo ""
echo "2️⃣  [Gather] Social Expert Intel..."
run_with_retry "Social Gather" python biostack_social.py --days "$DAYS"

echo ""
echo "3️⃣  [Gather] Nutrition Logs (MyNetDiary)..."
run_with_retry "Nutrition Gather" python biostack_nutrition.py --days "$DAYS"

echo ""
echo "4️⃣  [Gather] Vitals (Google Sheets)..."
run_with_retry "Vitals Gather" python biostack_vitals.py --days "$DAYS"

# 6. Execute Analyst (The Transformation Layer)
echo ""
echo "5️⃣  [Analyst] Generating Contextual Prompt..."
# Passing the template argument to the python script
run_with_retry "Analyst" python biostack_analyst.py --days "$DAYS" --template "$TEMPLATE"

# 7. Delivery
echo ""
echo "6️⃣  [Drive] Uploading Brief to Cloud..."
run_with_retry "Drive Upload" python biostack_drive.py --days "$DAYS"

echo ""
echo "🚀 BioStack Run Complete."
echo "=========================================="
