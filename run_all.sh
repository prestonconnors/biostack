#!/bin/bash

# 1. PREP: Set Directory to Script Location (Robust for Cron)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# 2. ACTIVATE PYTHON VENV
# Tries standard location name 'venv'
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "⚠️  Warning: Virtual Environment 'venv' not found. Trying global python..."
fi

# 3. ARGUMENT PARSING (Default: 8 days for full weekly overlap)
DAYS=8

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --days) DAYS="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

echo "=========================================="
echo "🧬 BIOSTACK: Starting Sync for past $DAYS days"
echo "   Date: $(date)"
echo "   Path: $(pwd)"
echo "=========================================="

# 4. EXECUTE GATHERERS (Continue even if one fails)
echo ""
echo "--- 1. FETCHING WHOOP DATA ---"
python biostack_whoop.py --days "$DAYS"

echo ""
echo "--- 2. FETCHING MYNETDIARY ---"
# Note: Selenium can be flaky; ensure display args or headless mode are set in py script
python biostack_nutrition.py --days "$DAYS"

echo ""
echo "--- 3. FETCHING GOOGLE SHEETS ---"
python biostack_vitals.py --days "$DAYS"

# 5. EXECUTE ANALYSIS (The Brain)
echo ""
echo "--- 4. ANALYZING DATA & PREPPING PROMPT ---"
# You can also pass a template here if you want to hardcode one, e.g. --template templates/coach.txt
python biostack_analyst.py --days "$DAYS"

# 6. DELIVERY
echo ""
echo "--- 5. UPLOADING TO DRIVE ---"
python biostack_drive.py --days "$DAYS"

echo ""
echo "✅ DONE. Pipeline Finished."