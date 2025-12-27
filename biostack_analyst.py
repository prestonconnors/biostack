import os
import json
import boto3
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, help='Start Date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End Date YYYY-MM-DD')
    parser.add_argument('--days', type=int, default=7, help='Days back')
    return parser.parse_args()

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-east-1'
    )

def get_latest_file_content(s3, folder):
    """ Reads newest S3 JSON file """
    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=folder)
        if 'Contents' not in response:
            return None 
        files = sorted(response['Contents'], key=lambda x: x['LastModified'])
        latest_file = files[-1]['Key']
        print(f"   Reading {folder}: {latest_file}...")
        
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=latest_file)
        return json.loads(obj['Body'].read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️  Error reading {folder}: {e}")
        return None

# --- POWER TOOLS: PRE-PROCESSING FUNCTIONS ---

def flatten_and_filter(data_list, start_date, end_date):
    """
    1. Converts dict-of-dicts to flat DataFrame using json_normalize
    2. Intelligent Date filtering
    """
    if not data_list or not isinstance(data_list, list):
        return pd.DataFrame()

    # MAGIC LINE: Flattens nested 'score.strain' -> 'score_strain'
    df = pd.json_normalize(data_list, sep='_')
    
    # Standardize Column Names (remove prefix/suffix clutter)
    df.columns = [c.replace('score_', '').replace('stage_summary_', '').lower() for c in df.columns]

    # Date Hunt
    date_col = None
    candidates = ['start', 'created_at', 'date', 'entrydate', 'cycle']
    for c in df.columns:
        if any(name in c for name in candidates):
            date_col = c
            # Break if we found a high quality one
            if 'start' in c or 'date' in c: break
    
    if not date_col:
        return df

    # Filter by Date
    try:
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce').dt.tz_localize(None)
        
        # Create a clean string 'Day' column for the AI
        df['day_str'] = df[date_col].dt.strftime('%Y-%m-%d')
        
        start = pd.to_datetime(start_date).replace(tzinfo=None)
        end = pd.to_datetime(end_date).replace(tzinfo=None) + timedelta(days=1)
        
        mask = (df[date_col] >= start) & (df[date_col] < end)
        df_filtered = df.loc[mask].copy()
        
        # Clean up the original dirty timestamp column to save tokens
        # The AI only needs 'day_str' usually
        return df_filtered.sort_values(by=date_col)
    except:
        return df

def aggregate_nutrition_dailies(df):
    """ Calculates Daily Macro Totals so ChatGPT doesn't have to add """
    if df.empty: return df, df

    # Identifying relevant numeric columns
    numeric_cols = ['calories', 'protein', 'fat', 'carbs', 'sugars', 'sodium', 'fiber', 'amount']
    # Filter only columns that actually exist
    cols_to_sum = [c for c in df.columns if any(x in c for x in numeric_cols)]
    
    # 1. DAILY SUMS
    if 'day_str' in df.columns:
        # Sum numeric columns by day
        # using 'min_count=0' ensures days present return 0 instead of NaN if empty
        daily_sums = df.groupby('day_str')[cols_to_sum].sum(numeric_only=True).reset_index()
    else:
        daily_sums = pd.DataFrame()

    # 2. RAW LOGS (Cleaned)
    # Only keep high-value columns for the "Event Log"
    keep_cols = ['day_str', 'name', 'meal', 'amount', 'calories', 'protein', 'fat', 'carbs']
    existing_keeps = [c for c in keep_cols if c in df.columns]
    raw_logs = df[existing_keeps].copy()

    return daily_sums, raw_logs

def clean_whoop_cycles(df):
    """ Selects only high-signal columns for Cycle Summary """
    if df.empty: return df
    
    keep = ['day_str', 'strain', 'kilojoule', 'average_heart_rate', 'max_heart_rate', 'recovery_score', 
            'hrv_rmssd_milli', 'resting_heart_rate', 'spo2_percentage', 'sleep_performance_percentage', 
            'sleep_efficiency_percentage', 'total_in_bed_time_milli']
    
    # Find which ones exist
    valid = [c for c in keep if c in df.columns]
    
    # Add simple conversions (e.g. milliseconds to hours)
    clean_df = df[valid].copy()
    if 'total_in_bed_time_milli' in clean_df.columns:
        clean_df['hours_sleep'] = round(clean_df['total_in_bed_time_milli'] / (1000 * 60 * 60), 2)
        clean_df = clean_df.drop(columns=['total_in_bed_time_milli'])

    return clean_df

def to_minified_json(df):
    """ Converts DF to string, handling NaNs and decimals """
    if df.empty: return "[]"
    # Round floats to 2 decimals to save tokens
    df = df.round(2)
    return df.to_json(orient='records')

def main():
    args = get_args()
    
    # Dates
    if args.end:
        end_date = datetime.strptime(args.end, '%Y-%m-%d')
    else:
        end_date = datetime.now()
    if args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
    else:
        start_date = end_date - timedelta(days=args.days)
        
    print(f"🧠 Biostack Analyst: {start_date.date()} -> {end_date.date()}")
    print("   (Fetching -> Flattening -> Aggregating)")

    s3 = get_s3_client()
    
    raw_whoop = get_latest_file_content(s3, 'whoop')
    raw_nutrition = get_latest_file_content(s3, 'nutrition')
    raw_vitals = get_latest_file_content(s3, 'vitals')

    prompt_data = []

    # --- 1. PRE-PROCESS NUTRITION ---
    if raw_nutrition:
        # Step A: Flatten Log
        flat_nut = flatten_and_filter(raw_nutrition, start_date, end_date)
        
        # Step B: Create Summary Table vs Event Log
        daily_macros, event_log = aggregate_nutrition_dailies(flat_nut)
        
        if not daily_macros.empty:
            prompt_data.append(f"<data name='nutrition_daily_totals'>\n{to_minified_json(daily_macros)}\n</data>")
        if not event_log.empty:
            prompt_data.append(f"<data name='nutrition_raw_log'>\n{to_minified_json(event_log)}\n</data>")

    # --- 2. PRE-PROCESS WHOOP ---
    if raw_whoop and isinstance(raw_whoop, dict):
        for category, records in raw_whoop.items():
            # Flatten (un-nest 'score' keys)
            df_flat = flatten_and_filter(records, start_date, end_date)
            
            # Specialized cleaning per type
            if category == 'recovery' or category == 'cycles' or category == 'sleep':
                df_flat = clean_whoop_cycles(df_flat)

            prompt_data.append(f"<data name='whoop_{category}'>\n{to_minified_json(df_flat)}\n</data>")
            
    # --- 3. PRE-PROCESS VITALS ---
    if raw_vitals:
        df_vitals = flatten_and_filter(raw_vitals, start_date, end_date)
        prompt_data.append(f"<data name='vitals'>\n{to_minified_json(df_vitals)}\n</data>")

    # --- 4. CONSTRUCT THE SUPER PROMPT ---
    final_prompt = f"""
I am an elite performance coach. I have pre-calculated your daily statistics to analyze your correlations faster.

### MISSION
1. Review the **Daily Totals** for trends (Load vs Recovery vs Calories).
2. Scan the **Raw Logs** only for specific details (e.g. "What meal caused the high sugar spike?").
3. Analyze `whoop_recovery` lag: Compare NUTRITION on Day X to RECOVERY on Day X+1.
4. Provide 3 specific protocols for next week.

---
PRE-PROCESSED DATASET:

{chr(10).join(prompt_data)}
"""

    filename = "biostack_prompt.txt"
    with open(filename, "w", encoding='utf-8') as f:
        f.write(final_prompt)
    
    print(f"\n✅ OPTIMIZED PROMPT SAVED: {filename}")
    print("   -> Data is flattened and summed. Thinking time should be minimized.")

if __name__ == "__main__":
    main()