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

# 2. Parse Arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -t|--template) TEMPLATE="$2"; shift ;;
        -d|--days) DAYS="$2"; shift ;;
        *) echo "❌ Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

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
python biostack_whoop.py --days "$DAYS"

echo ""
echo "2️⃣  [Gather] Social Expert Intel..."
python biostack_social.py --days "$DAYS"

echo ""
echo "3️⃣  [Gather] Nutrition Logs (MyNetDiary)..."
python biostack_nutrition.py --days "$DAYS"

echo ""
echo "4️⃣  [Gather] Vitals (Google Sheets)..."
python biostack_vitals.py --days "$DAYS"

# 6. Execute Analyst (The Transformation Layer)
echo ""
echo "5️⃣  [Analyst] Generating Contextual Prompt..."
# Passing the template argument to the python script
python biostack_analyst.py --days "$DAYS" --template "$TEMPLATE"

# 7. Delivery
echo ""
echo "6️⃣  [Drive] Uploading Brief to Cloud..."
python biostack_drive.py --days "$DAYS"

echo ""
echo "🚀 BioStack Run Complete."
echo "=========================================="
