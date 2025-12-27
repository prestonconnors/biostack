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
    parser.add_argument('--days', type=int, default=7, help='Days back to analyze (default: 7)')
    return parser.parse_args()

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-east-1'
    )

def get_latest_file_content(s3, folder):
    """ Finds the most recently uploaded file in a specific S3 folder and reads it """
    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=folder)
        if 'Contents' not in response:
            print(f"⚠️  No data found in '{folder}/'")
            return []
        
        # Sort by LastModified date (newest last)
        files = sorted(response['Contents'], key=lambda x: x['LastModified'])
        latest_file = files[-1]['Key']
        
        print(f"   Reading latest {folder} file: {latest_file}...")
        
        obj = s3.get_object(Bucket=BUCKET_NAME, Key=latest_file)
        content = json.loads(obj['Body'].read().decode('utf-8'))
        return content
    except Exception as e:
        print(f"❌ Error reading {folder}: {e}")
        return []

def filter_data_by_date(data, start_date, end_date):
    """ Converts list of dicts to DataFrame and filters by date range """
    if not data:
        return pd.DataFrame()
    
    df = pd.DataFrame(data)
    
    # Intelligent Date Detection
    date_col = None
    possible_names = ['date', 'Date', 'cycle', 'Cycle', 'entryDate', 'day']
    
    for col in df.columns:
        if any(name in col for name in possible_names):
            date_col = col
            break
            
    if not date_col:
        print("⚠️  Warning: Could not find a date column in data. Using all data.")
        return df

    # Normalize Dates
    # Some dates are ISO strings, some are simple YYYY-MM-DD
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce').dt.tz_localize(None) # Remove timezone for easy compare
    
    # Filter
    # Ensure strict comparison by normalizing filter dates to midnight
    start = pd.to_datetime(start_date).replace(hour=0, minute=0, second=0, microsecond=0)
    end = pd.to_datetime(end_date).replace(hour=23, minute=59, second=59, microsecond=999999)
    
    mask = (df[date_col] >= start) & (df[date_col] <= end)
    filtered = df.loc[mask]
    
    return filtered

def generate_prompt(whoop_df, nutrition_df, vitals_df, start_date, end_date):
    """ Constructs the Engineering Prompt """
    
    # Prepare Aggregates
    stats = []
    
    if not whoop_df.empty:
        # Whoop: Interested in Avg Recovery, Strain, Sleep
        # Flatten structure if nested? Usually MyNetDiary/Whoop flat structures work best
        stats.append(f"## WHOOP DATA (Physiology)\n{whoop_df.to_markdown(index=False)}")
    else:
        stats.append("## WHOOP DATA\n(No data found for this period)")

    if not nutrition_df.empty:
        # Select key columns to keep token count low if desired
        # If massive, maybe group by date?
        # For now, we dump the log
        cols = [c for c in nutrition_df.columns if 'date' in c.lower() or 'cal' in c.lower() or 'prot' in c.lower() or 'fat' in c.lower() or 'carb' in c.lower()]
        display_df = nutrition_df[cols] if cols else nutrition_df
        stats.append(f"## NUTRITION DATA\n{display_df.to_markdown(index=False)}")
    else:
        stats.append("## NUTRITION DATA\n(No data found for this period)")
        
    if not vitals_df.empty:
        stats.append(f"## VITALS & BODY DATA\n{vitals_df.to_markdown(index=False)}")
    else:
        stats.append("## VITALS DATA\n(No data found for this period)")

    # Construct the Prompt Text
    prompt = f"""
I am going to provide you with my personal health data for the period of {start_date.date()} to {end_date.date()}.

ROLE:
Act as an elite Performance Coach and Clinical Nutritionist. Your goal is to analyze the correlations between my INPUTS (Nutrition) and my OUTPUTS (Whoop recovery, Strain, Weight, Blood Pressure, Skeletal Muscle Mass).

DATA:

{stats[0]}

{stats[1]}

{stats[2]}

TASK:
1. **Trend Analysis:** Identify specific patterns between my nutrition/macros and my next-day recovery or blood pressure.
2. **Anomaly Detection:** Highlight any days where vitals deviated significantly and hypothesize the cause based on the other data.
3. **Actionable Protocol:** Based on this specific week of data, provide 3 distinct actionable steps for next week to optimize recovery and body composition (Muscle Mass).
"""
    return prompt

def main():
    args = get_args()
    
    # Calculate Dates
    if args.end:
        end_date = datetime.strptime(args.end, '%Y-%m-%d')
    else:
        end_date = datetime.now()

    if args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
    else:
        start_date = end_date - timedelta(days=args.days)
        
    print(f"📊 Analyzing BioStack Data: {start_date.date()} -> {end_date.date()}...\n")

    s3 = get_s3_client()
    
    # 1. Fetch Latest Dumps
    raw_whoop = get_latest_file_content(s3, 'whoop')
    raw_nutrition = get_latest_file_content(s3, 'nutrition')
    raw_vitals = get_latest_file_content(s3, 'vitals')
    
    # 2. Filter to Timeframe
    whoop_df = filter_data_by_date(raw_whoop, start_date, end_date)
    nutrition_df = filter_data_by_date(raw_nutrition, start_date, end_date)
    vitals_df = filter_data_by_date(raw_vitals, start_date, end_date)
    
    print(f"   Found {len(whoop_df)} Whoop logs.")
    print(f"   Found {len(nutrition_df)} Nutrition logs.")
    print(f"   Found {len(vitals_df)} Vitals logs.")
    
    # 3. Build Prompt
    final_prompt = generate_prompt(whoop_df, nutrition_df, vitals_df, start_date, end_date)
    
    # 4. Output
    filename = "biostack_prompt.txt"
    with open(filename, "w", encoding='utf-8') as f:
        f.write(final_prompt)
        
    print(f"\n✅ Prompt generated! saved to: {filename}")
    print("-" * 30)
    print("Next step: Open 'biostack_prompt.txt', Copy All, and Paste into ChatGPT.")

if __name__ == "__main__":
    main()