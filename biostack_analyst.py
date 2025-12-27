import os
import json
import boto3
import argparse
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

BUCKET_NAME = os.getenv('BIOSTACK_BUCKET_NAME')

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, help='Start Date YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='End Date YYYY-MM-DD')
    parser.add_argument('--days', type=int, default=7, help='Days back')
    # NEW ARGUMENT
    parser.add_argument('--template', type=str, default='templates/default_coach.txt', 
                        help='Path to text file containing prompt logic (must include {{DATASET}} placeholder)')
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

    df = pd.json_normalize(data_list, sep='_')
    df.columns = [c.replace('score_', '').replace('stage_summary_', '').lower() for c in df.columns]

    date_col = None
    candidates = ['start', 'created_at', 'date', 'entrydate', 'cycle']
    for c in df.columns:
        if any(name in c for name in candidates):
            date_col = c
            if 'start' in c or 'date' in c: break
    
    if not date_col:
        return df

    try:
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce').dt.tz_localize(None)
        df['day_str'] = df[date_col].dt.strftime('%Y-%m-%d')
        
        start = pd.to_datetime(start_date).replace(tzinfo=None)
        end = pd.to_datetime(end_date).replace(tzinfo=None) + timedelta(days=1)
        
        mask = (df[date_col] >= start) & (df[date_col] < end)
        df_filtered = df.loc[mask].copy()
        return df_filtered.sort_values(by=date_col)
    except:
        return df

def aggregate_nutrition_dailies(df):
    """ Calculates Daily Macro Totals """
    if df.empty: return df, df

    numeric_cols = ['calories', 'protein', 'fat', 'carbs', 'sugars', 'sodium', 'fiber', 'amount']
    cols_to_sum = [c for c in df.columns if any(x in c for x in numeric_cols)]
    
    if 'day_str' in df.columns:
        daily_sums = df.groupby('day_str')[cols_to_sum].sum(numeric_only=True).reset_index()
    else:
        daily_sums = pd.DataFrame()

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
    
    valid = [c for c in keep if c in df.columns]
    clean_df = df[valid].copy()
    
    if 'total_in_bed_time_milli' in clean_df.columns:
        clean_df['hours_sleep'] = round(clean_df['total_in_bed_time_milli'] / (1000 * 60 * 60), 2)
        clean_df = clean_df.drop(columns=['total_in_bed_time_milli'])

    return clean_df

def to_minified_json(df):
    if df.empty: return "[]"
    df = df.round(2)
    return df.to_json(orient='records')

def load_template_string(path):
    """ Safe Loader for Template """
    if os.path.exists(path):
        print(f"📄 Using Prompt Template: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        print(f"⚠️ Template file not found: {path}")
        print("   -> Fallback: Using default internal minimal prompt.")
        return """DATA ANALYSIS REQUEST:\n\n{{DATASET}}"""

def main():
    args = get_args()
    
    if args.end:
        end_date = datetime.strptime(args.end, '%Y-%m-%d')
    else:
        end_date = datetime.now()
    if args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
    else:
        start_date = end_date - timedelta(days=args.days)
        
    print(f"🧠 Biostack Analyst: {start_date.date()} -> {end_date.date()}")
    
    s3 = get_s3_client()
    raw_whoop = get_latest_file_content(s3, 'whoop')
    raw_nutrition = get_latest_file_content(s3, 'nutrition')
    raw_vitals = get_latest_file_content(s3, 'vitals')

    prompt_data = []

    # --- 1. NUTRITION ---
    if raw_nutrition:
        flat_nut = flatten_and_filter(raw_nutrition, start_date, end_date)
        daily_macros, event_log = aggregate_nutrition_dailies(flat_nut)
        if not daily_macros.empty:
            prompt_data.append(f"<data name='nutrition_daily_totals'>\n{to_minified_json(daily_macros)}\n</data>")
        if not event_log.empty:
            prompt_data.append(f"<data name='nutrition_raw_log'>\n{to_minified_json(event_log)}\n</data>")

    # --- 2. WHOOP ---
    if raw_whoop and isinstance(raw_whoop, dict):
        for category, records in raw_whoop.items():
            df_flat = flatten_and_filter(records, start_date, end_date)
            if category in ['recovery', 'cycles', 'sleep']:
                df_flat = clean_whoop_cycles(df_flat)
            prompt_data.append(f"<data name='whoop_{category}'>\n{to_minified_json(df_flat)}\n</data>")
            
    # --- 3. VITALS ---
    if raw_vitals:
        df_vitals = flatten_and_filter(raw_vitals, start_date, end_date)
        prompt_data.append(f"<data name='vitals'>\n{to_minified_json(df_vitals)}\n</data>")

    # --- 4. CONSTRUCT PROMPT FROM TEMPLATE ---
    data_block = "\n".join(prompt_data)
    template_content = load_template_string(args.template)
    
    # Safe Replacement (Use .replace, not f-string, to avoid curly brace errors in templates)
    if "{{DATASET}}" in template_content:
        final_prompt = template_content.replace("{{DATASET}}", data_block)
    else:
        # Fallback if user forgot the tag
        final_prompt = template_content + "\n\n" + data_block

    filename = "biostack_prompt.txt"
    with open(filename, "w", encoding='utf-8') as f:
        f.write(final_prompt)
    
    print(f"\n✅ OPTIMIZED PROMPT SAVED: {filename}")

if __name__ == "__main__":
    main()