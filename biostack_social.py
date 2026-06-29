import os
import json
import time
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

import boto3
import requests
from botocore.exceptions import ClientError
from dotenv import load_dotenv


# -----------------------------------------------------------------------------
# biostack_social.py
#
# Official X API version.
#
# Cost-control strategy:
#   1. Use Recent Search with query: from:handle -is:retweet -is:reply
#      instead of user lookup + per-user timeline.
#   2. Cache newest seen Post IDs using since_id.
#   3. Cache locally and in S3 so different machines/cron runs do not re-read.
#   4. Default to one page per handle and small max_results.
#
# Required .env:
#   X_BEARER_TOKEN=...
#   BIOSTACK_BUCKET_NAME=...
#   X_FOLLOW_LIST=bryan_johnson,hubermanlab
#
# Optional .env:
#   BIOSTACK_SOCIAL_CACHE_KEY=social/social_cache.json
#   BIOSTACK_SOCIAL_OUTPUT_PREFIX=social
#   X_MAX_RESULTS=10
#   X_MAX_PAGES=1
# -----------------------------------------------------------------------------


load_dotenv()

X_API_BASE = "https://api.x.com/2"

BEARER_TOKEN = (
    os.getenv("X_BEARER_TOKEN")
    or os.getenv("X_API_BEARER_TOKEN")
    or os.getenv("TWITTER_BEARER_TOKEN")
)

BUCKET_NAME = os.getenv("BIOSTACK_BUCKET_NAME")

OUTPUT_PREFIX = os.getenv("BIOSTACK_SOCIAL_OUTPUT_PREFIX", "social").strip("/")

CACHE_KEY = os.getenv(
    "BIOSTACK_SOCIAL_CACHE_KEY",
    f"{OUTPUT_PREFIX}/social_cache.json",
)

LOCAL_CACHE_FILE = "social_cache.json"

HANDLES = [
    h.strip().lstrip("@")
    for h in os.getenv("X_FOLLOW_LIST", "").split(",")
    if h.strip()
]


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch recent posts from selected X accounts using the official X API."
    )

    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Lookback window for first run or when no since_id is cached. Recent Search supports up to 7 days.",
    )

    parser.add_argument(
        "--max-results",
        type=int,
        default=int(os.getenv("X_MAX_RESULTS", "10")),
        help="Max posts returned per request. Recent Search commonly supports 10-100.",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=int(os.getenv("X_MAX_PAGES", "1")),
        help="Max pages to fetch per handle. Keep low for cost control.",
    )

    parser.add_argument(
        "--include-replies",
        action="store_true",
        help="Include replies. Default excludes replies to reduce noise/cost.",
    )

    parser.add_argument(
        "--include-retweets",
        action="store_true",
        help="Include retweets/reposts. Default excludes retweets to reduce noise/cost.",
    )

    parser.add_argument(
        "--force-full-scan",
        action="store_true",
        help="Ignore cached since_id and scan by --days. This can cost more.",
    )

    parser.add_argument(
        "--no-s3-cache",
        action="store_true",
        help="Do not download/upload cache from S3. Local cache still used.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print results but do not upload intel/cache to S3.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print request/debug details.",
    )

    return parser.parse_args()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def clamp_days(days: int) -> int:
    # X Recent Search covers up to the last 7 days.
    return max(1, min(days, 7))


def clamp_max_results(value: int) -> int:
    # X Recent Search generally accepts 10-100.
    if value < 10:
        return 10
    if value > 100:
        return 100
    return value


def normalize_handle(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def get_s3_client():
    return boto3.client("s3")


def blank_cache() -> Dict[str, Any]:
    return {
        "version": 2,
        "updated_at": None,
        "handles": {},
    }


def normalize_cache(cache: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(cache, dict):
        cache = blank_cache()

    cache.setdefault("version", 2)
    cache.setdefault("updated_at", None)
    cache.setdefault("handles", {})

    normalized_handles = {}

    for handle, data in cache.get("handles", {}).items():
        h = normalize_handle(handle)

        if not isinstance(data, dict):
            data = {}

        seen_ids = data.get("seen_ids", [])
        if not isinstance(seen_ids, list):
            seen_ids = []

        normalized_handles[h] = {
            "since_id": data.get("since_id"),
            "seen_ids": [str(x) for x in seen_ids][-500:],
            "last_checked_at": data.get("last_checked_at"),
            "last_result_count": data.get("last_result_count", 0),
            "last_capped_at": data.get("last_capped_at"),
        }

    cache["handles"] = normalized_handles
    return cache


def load_local_cache(cache_file: str = LOCAL_CACHE_FILE) -> Dict[str, Any]:
    if not os.path.exists(cache_file):
        return blank_cache()

    try:
        with open(cache_file, "r") as f:
            return normalize_cache(json.load(f))
    except Exception as e:
        print(f"⚠️ Could not read local cache {cache_file}: {e}")
        return blank_cache()


def save_local_cache(cache: Dict[str, Any], cache_file: str = LOCAL_CACHE_FILE) -> None:
    try:
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2, sort_keys=True)

        print(f"💾 Saved local cache: {cache_file}")

    except Exception as e:
        print(f"⚠️ Could not save local cache {cache_file}: {e}")


def load_s3_json(bucket: str, key: str) -> Optional[Dict[str, Any]]:
    try:
        s3 = get_s3_client()
        obj = s3.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        return json.loads(body)

    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")

        if code in ("NoSuchKey", "404", "NotFound"):
            return None

        print(f"⚠️ Could not load s3://{bucket}/{key}: {e}")
        return None

    except Exception as e:
        print(f"⚠️ Could not load s3://{bucket}/{key}: {e}")
        return None


def upload_s3_json(bucket: str, key: str, payload: Dict[str, Any]) -> None:
    s3 = get_s3_client()

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, indent=2, sort_keys=True),
        ContentType="application/json",
    )


def load_cache(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Prefer S3 cache when available so cron/local runs share since_id state.
    Fall back to local cache.
    """
    if BUCKET_NAME and not args.no_s3_cache:
        s3_cache = load_s3_json(BUCKET_NAME, CACHE_KEY)

        if s3_cache:
            print(f"☁️ Loaded cache from s3://{BUCKET_NAME}/{CACHE_KEY}")
            return normalize_cache(s3_cache)

    local_cache = load_local_cache()

    if local_cache.get("handles"):
        print(f"💾 Loaded local cache from {LOCAL_CACHE_FILE}")
    else:
        print("ℹ️ No existing cache found. First run will scan by --days.")

    return normalize_cache(local_cache)


def save_cache(cache: Dict[str, Any], args: argparse.Namespace) -> None:
    cache["updated_at"] = iso_utc(now_utc())

    save_local_cache(cache)

    if args.dry_run:
        print("🧪 Dry run: skipped S3 cache upload.")
        return

    if BUCKET_NAME and not args.no_s3_cache:
        try:
            upload_s3_json(BUCKET_NAME, CACHE_KEY, cache)
            print(f"☁️ Uploaded cache: s3://{BUCKET_NAME}/{CACHE_KEY}")

        except Exception as e:
            print(f"⚠️ Could not upload cache to S3: {e}")


def make_session() -> requests.Session:
    if not BEARER_TOKEN:
        raise RuntimeError(
            "Missing X_BEARER_TOKEN in .env. Add your official X API Bearer Token."
        )

    session = requests.Session()

    session.headers.update(
        {
            "Authorization": f"Bearer {BEARER_TOKEN}",
            "User-Agent": "biostack-social-official-xapi/1.0",
        }
    )

    return session


def format_x_api_error(response: requests.Response, payload: Dict[str, Any]) -> str:
    if "detail" in payload:
        return payload["detail"]

    if "title" in payload or "reason" in payload:
        return json.dumps(payload, indent=2)

    if "errors" in payload:
        return json.dumps(payload["errors"], indent=2)

    return json.dumps(payload, indent=2)


def x_get(
    session: requests.Session,
    path: str,
    params: Dict[str, Any],
    debug: bool = False,
) -> Dict[str, Any]:
    url = f"{X_API_BASE}{path}"

    if debug:
        print(f"   GET {url}")
        print(f"   params={json.dumps(params, indent=2)}")

    response = session.get(url, params=params, timeout=30)

    if response.status_code == 429:
        reset = response.headers.get("x-rate-limit-reset")
        reset_msg = ""

        if reset and reset.isdigit():
            reset_dt = datetime.fromtimestamp(int(reset), tz=timezone.utc)
            reset_msg = f" Rate limit resets at {iso_utc(reset_dt)}."

        raise RuntimeError(f"X API rate limit hit.{reset_msg}")

    try:
        payload = response.json()
    except Exception:
        payload = {"raw_response": response.text[:1000]}

    if not response.ok:
        raise RuntimeError(
            f"X API error {response.status_code}: {format_x_api_error(response, payload)}"
        )

    return payload


def build_query(
    handle: str,
    include_replies: bool = False,
    include_retweets: bool = False,
) -> str:
    parts = [f"from:{handle}"]

    if not include_retweets:
        parts.append("-is:retweet")

    if not include_replies:
        parts.append("-is:reply")

    return " ".join(parts)


def get_handle_cache(cache: Dict[str, Any], handle: str) -> Dict[str, Any]:
    h = normalize_handle(handle)

    cache["handles"].setdefault(
        h,
        {
            "since_id": None,
            "seen_ids": [],
            "last_checked_at": None,
            "last_result_count": 0,
            "last_capped_at": None,
        },
    )

    return cache["handles"][h]


def choose_start_time(days: int) -> str:
    safe_days = clamp_days(days)
    return iso_utc(now_utc() - timedelta(days=safe_days))


def tweet_text(tweet: Dict[str, Any]) -> str:
    return tweet.get("text", "")


def tweet_to_intel(handle: str, tweet: Dict[str, Any]) -> Dict[str, Any]:
    metrics = tweet.get("public_metrics") or {}
    tweet_id = str(tweet.get("id"))

    return {
        "id": tweet_id,
        "ts": tweet.get("created_at"),
        "content": tweet_text(tweet).replace("\n", " ").strip(),
        "likes": metrics.get("like_count", 0),
        "retweets": metrics.get("retweet_count", 0),
        "replies": metrics.get("reply_count", 0),
        "quotes": metrics.get("quote_count", 0),
        "bookmarks": metrics.get("bookmark_count", 0),
        "impressions": metrics.get("impression_count", 0),
        "url": f"https://x.com/{handle}/status/{tweet_id}",
    }


def max_tweet_id(tweets: List[Dict[str, Any]]) -> Optional[str]:
    ids = []

    for tweet in tweets:
        try:
            ids.append(int(tweet["id"]))
        except Exception:
            continue

    if not ids:
        return None

    return str(max(ids))


def fetch_recent_posts_for_handle(
    session: requests.Session,
    handle: str,
    cache: Dict[str, Any],
    args: argparse.Namespace,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Returns:
      tweets: list of tweet/post objects
      capped: True if there were more pages but --max-pages stopped us
    """
    handle_norm = normalize_handle(handle)
    handle_state = get_handle_cache(cache, handle_norm)

    query = build_query(
        handle=handle_norm,
        include_replies=args.include_replies,
        include_retweets=args.include_retweets,
    )

    params: Dict[str, Any] = {
        "query": query,
        "max_results": clamp_max_results(args.max_results),
        "tweet.fields": ",".join(
            [
                "id",
                "text",
                "created_at",
                "author_id",
                "public_metrics",
                "referenced_tweets",
                "lang",
            ]
        ),
    }

    since_id = handle_state.get("since_id")

    if since_id and not args.force_full_scan:
        params["since_id"] = since_id

        if args.debug:
            print(f"   using cached since_id={since_id}")

    else:
        params["start_time"] = choose_start_time(args.days)

        if args.force_full_scan:
            print(f"   ⚠️ Force full scan for @{handle_norm}; ignoring cached since_id.")
        elif args.days > 7:
            print("   ℹ️ Recent Search only covers the last 7 days. Capping lookback to 7 days.")

    all_tweets: List[Dict[str, Any]] = []
    next_token = None
    capped = False

    max_pages = max(1, args.max_pages)

    for page_num in range(1, max_pages + 1):
        page_params = dict(params)

        if next_token:
            page_params["next_token"] = next_token

        payload = x_get(
            session=session,
            path="/tweets/search/recent",
            params=page_params,
            debug=args.debug,
        )

        data = payload.get("data") or []
        meta = payload.get("meta") or {}

        if args.debug:
            print(f"   page {page_num}: result_count={meta.get('result_count', len(data))}")

        all_tweets.extend(data)

        next_token = meta.get("next_token")

        if not next_token:
            capped = False
            break

        if page_num == max_pages and next_token:
            capped = True

    return all_tweets, capped


def dedupe_new_tweets(
    handle: str,
    tweets: List[Dict[str, Any]],
    cache: Dict[str, Any],
) -> List[Dict[str, Any]]:
    handle_state = get_handle_cache(cache, handle)
    seen_ids = set(str(x) for x in handle_state.get("seen_ids", []))

    deduped = []

    for tweet in tweets:
        tweet_id = str(tweet.get("id"))

        if not tweet_id:
            continue

        if tweet_id in seen_ids:
            continue

        seen_ids.add(tweet_id)
        deduped.append(tweet)

    deduped.sort(key=lambda t: int(t["id"]), reverse=True)

    handle_state["seen_ids"] = list(seen_ids)[-500:]

    return deduped


def update_handle_cache(
    handle: str,
    raw_tweets: List[Dict[str, Any]],
    cache: Dict[str, Any],
    capped: bool,
) -> None:
    handle_state = get_handle_cache(cache, handle)
    handle_state["last_checked_at"] = iso_utc(now_utc())
    handle_state["last_result_count"] = len(raw_tweets)

    if not raw_tweets:
        return

    newest_id = max_tweet_id(raw_tweets)

    if not newest_id:
        return

    # Cost-first behavior:
    # If --max-pages capped the run, advancing since_id means older posts beyond
    # the page cap are intentionally skipped. This avoids paying to re-read the
    # same newest posts forever. Increase --max-pages if full catch-up matters.
    handle_state["since_id"] = newest_id

    if capped:
        handle_state["last_capped_at"] = iso_utc(now_utc())


def merge_daily_intel(
    existing: Optional[Dict[str, Any]],
    new_data: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Merge into the existing daily S3 JSON so multiple runs/day do not overwrite
    earlier posts.
    """
    if not isinstance(existing, dict):
        existing = {}

    merged: Dict[str, List[Dict[str, Any]]] = {}

    for handle, posts in existing.items():
        if isinstance(posts, list):
            merged[handle] = posts

    for handle, posts in new_data.items():
        merged.setdefault(handle, [])

        seen = {
            str(post.get("id") or post.get("url"))
            for post in merged[handle]
            if isinstance(post, dict)
        }

        for post in posts:
            post_key = str(post.get("id") or post.get("url"))

            if post_key not in seen:
                merged[handle].append(post)
                seen.add(post_key)

        merged[handle].sort(
            key=lambda p: p.get("ts") or "",
            reverse=True,
        )

    return merged


def upload_intel(
    master_intel: Dict[str, List[Dict[str, Any]]],
    args: argparse.Namespace,
) -> None:
    if not master_intel:
        print("⚠️ No new social intel collected. Nothing to upload.")
        return

    if args.dry_run:
        print("🧪 Dry run: skipping S3 upload. Collected data:")
        print(json.dumps(master_intel, indent=2))
        return

    if not BUCKET_NAME:
        print("❌ S3 upload skipped: BIOSTACK_BUCKET_NAME is missing from .env")
        print(json.dumps(master_intel, indent=2))
        return

    date_str = now_utc().strftime("%Y%m%d")
    output_key = f"{OUTPUT_PREFIX}/social_intel_{date_str}.json"

    try:
        existing = load_s3_json(BUCKET_NAME, output_key)
        merged = merge_daily_intel(existing, master_intel)

        upload_s3_json(BUCKET_NAME, output_key, merged)

        new_count = sum(len(v) for v in master_intel.values())
        merged_count = sum(len(v) for v in merged.values())

        print(f"🚀 SUCCESS: s3://{BUCKET_NAME}/{output_key}")
        print(f"   New posts this run: {new_count}")
        print(f"   Total posts in daily file: {merged_count}")

    except Exception as e:
        print(f"❌ S3 Upload Failed: {e}")
        print("Collected data:")
        print(json.dumps(master_intel, indent=2))


def main() -> None:
    args = get_args()

    if not HANDLES:
        print("❌ No handles found.")
        print("   Add X_FOLLOW_LIST to your .env, for example:")
        print("   X_FOLLOW_LIST=bryan_johnson,hubermanlab")
        return

    if not BEARER_TOKEN:
        print("❌ Missing X_BEARER_TOKEN in .env.")
        print("   Add your official X API Bearer Token:")
        print("   X_BEARER_TOKEN=...")
        return

    print("📡 Authenticating with official X API Bearer Token...")

    try:
        session = make_session()
    except Exception as e:
        print(f"❌ Could not create X API session: {e}")
        return

    cache = load_cache(args)
    master_intel: Dict[str, List[Dict[str, Any]]] = {}

    success_count = 0
    error_count = 0

    print(f"📋 Handles: {', '.join('@' + normalize_handle(h) for h in HANDLES)}")
    print(
        f"💸 Cost controls: "
        f"max_results={clamp_max_results(args.max_results)}, "
        f"max_pages={max(1, args.max_pages)}"
    )
    print(f"🧹 Excluding replies: {not args.include_replies}")
    print(f"🧹 Excluding retweets: {not args.include_retweets}")

    for raw_handle in HANDLES:
        handle = normalize_handle(raw_handle)

        print(f"📡 Processing @{handle}...")

        try:
            raw_tweets, capped = fetch_recent_posts_for_handle(
                session=session,
                handle=handle,
                cache=cache,
                args=args,
            )

            success_count += 1

            new_tweets = dedupe_new_tweets(
                handle=handle,
                tweets=raw_tweets,
                cache=cache,
            )

            update_handle_cache(
                handle=handle,
                raw_tweets=raw_tweets,
                cache=cache,
                capped=capped,
            )

            if capped:
                print(
                    f"   ⚠️ Hit --max-pages for @{handle}. "
                    f"Older matching posts may have been skipped to control cost. "
                    f"Increase --max-pages if you want fuller catch-up."
                )

            if new_tweets:
                intel = [tweet_to_intel(handle, tweet) for tweet in new_tweets]
                master_intel[handle] = intel

                print(f"   ✅ New posts: {len(intel)}")

                if args.debug:
                    for item in intel[:5]:
                        preview = item["content"][:100]
                        print(f"   [+] {item['ts']} | {preview}...")
            else:
                print("   ⚠️ No new posts found.")

            time.sleep(0.5)

        except Exception as e:
            error_count += 1
            print(f"   ❌ Error processing @{handle}: {e}")

    if success_count == 0 and error_count > 0:
        print("❌ All X API requests failed. Not updating cache or uploading intel.")
        return

    save_cache(cache, args)
    upload_intel(master_intel, args)


if __name__ == "__main__":
    main()
