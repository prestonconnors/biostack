#!/bin/bash

# 1. Dynamically find the folder this script is sitting in
#    This allows the script to run correctly even if called via Cron from a different path.
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 2. Go to that directory
cd "$PROJECT_ROOT"

# 3. Smart Python Detection
#    Checks standard locations for the virtual environment
if [ -f "$PROJECT_ROOT/venv/bin/python" ]; then
    PYTHON_BIN="$PROJECT_ROOT/venv/bin/python"
elif [ -f "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
    # Fallback to system python if no venv found
    echo "⚠️  Virtual Environment not detected. Using system python3."
    PYTHON_BIN="python3"
fi

# 4. Safety Check for Credentials
if [ ! -f ".env" ]; then
    echo "❌ CRITICAL: No .env file found in $PROJECT_ROOT."
    echo "   Please create one (or rename .env.example) before running."
    exit 1
fi

# 5. Execution
echo "================================================"
echo "🚀 Starting BioStack Run"
echo "📅 Date: $(date)"
echo "📂 Location: $PROJECT_ROOT"
echo "🐍 Python: $PYTHON_BIN"
echo "================================================"

# Execute Scripts
echo ">> Step 1: Fetching Whoop Data..."
$PYTHON_BIN biostack_whoop.py --days 8
echo "--------------------------------"

echo ">> Step 2: Fetching Nutrition Data..."
$PYTHON_BIN biostack_nutrition.py --days 8
echo "--------------------------------"

echo ">> Step 3: Fetching Vitals Data..."
$PYTHON_BIN biostack_vitals.py --days 8
echo "--------------------------------"

echo ">> Step 4: Analyzing Data & Generating Prompt..."
$PYTHON_BIN biostack_analyst.py --days 8
echo "--------------------------------"

echo "✅ Run Complete. Results saved to $PROJECT_ROOT/biostack_prompt.txt"