"""
Complete User Metrics Script
=============================
This script completes the GitHub user data extraction by adding missing metrics.

Purpose:
- Add PRIMARY LANGUAGE to each user (currently missing from users.csv)
- Create complete activity dataset with proper documentation of limitations

Approach:
- Reads existing users.csv (1,000 users already extracted)
- Does NOT re-extract users from /users endpoint
- Only makes additional API calls needed for missing data

Primary Language Calculation:
- Fetches all public repositories for each user
- Counts repositories by language
- Primary language = language appearing in most repositories
- If no language data, sets to empty string

Recent Commit Activity:
- Uses existing activity.csv data
- Documents GitHub API limitation (~30 most recent public events only)
- Creates activity_complete.csv with all 1,000 users

Output Files:
- users_complete.csv: Original users.csv + primary_language column
- activity_complete.csv: Complete activity data for all 1,000 users
"""

import os
import csv
import requests
from dotenv import load_dotenv
import time
from datetime import datetime

load_dotenv()

token = os.getenv("github_token")

if not token:
    raise ValueError("Github token was not found in the .env file")

# Request headers
headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {token}"
}

def make_request_with_retry(url, headers, params=None, max_retries=3):
    """Make API request with retry logic and rate limit handling"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            # Rate-limit management
            if response.status_code == 403:
                if 'X-RateLimit-Remaining' in response.headers and response.headers['X-RateLimit-Remaining'] == '0':
                    reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                    wait_time = reset_time - int(time.time())
                    if wait_time > 0:
                        print(f"  [!] Rate limit exceeded. Waiting {wait_time} seconds...")
                        time.sleep(wait_time + 1)
                        continue
            
            return response
            
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries - 1:
                print(f"  [!] Request failed (attempt {attempt + 1}/{max_retries}), retrying...")
                time.sleep(2)
            else:
                print(f"  [!] Request failed after {max_retries} attempts")
                return None
    
    return None

def get_primary_language(username, headers):
    """
    Determine user's primary programming language from their repositories.
    
    Rule:
    1. Fetch ALL public repositories (with pagination)
    2. Count repositories by language (ignore null)
    3. Primary language = language with most repositories
    4. If tied, select alphabetically first
    5. If no language data, return empty string
    
    Returns:
        str: Primary language or empty string
    """
    repos_url = f"https://api.github.com/users/{username}/repos"
    languages = {}
    page = 1
    
    while True:
        params = {"per_page": 100, "page": page}
        response = make_request_with_retry(repos_url, headers, params)
        
        if not response or response.status_code != 200:
            if page == 1:
                print(f"    [!] Could not fetch repositories")
            return ""
        
        repos = response.json()
        if not repos:
            break
        
        # Count languages
        for repo in repos:
            language = repo.get("language")
            if language:  # Ignore null languages
                languages[language] = languages.get(language, 0) + 1
        
        page += 1
        
        # Stop if we got fewer than 100 repos (last page)
        if len(repos) < 100:
            break
    
    # Determine primary language
    if not languages:
        return ""
    
    # Get language with most repos (alphabetically first if tied)
    primary = max(languages.items(), key=lambda x: (x[1], -ord(x[0][0])))
    return primary[0]

def main():
    print("="*70)
    print("COMPLETE USER METRICS EXTRACTION")
    print("="*70)
    print()
    
    # Read existing users.csv
    print("[1/4] Reading existing users.csv...")
    users = []
    with open("users.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        users = list(reader)
    
    print(f"  [+] Loaded {len(users)} users")
    print()
    
    # Read existing activity.csv
    print("[2/4] Reading existing activity.csv...")
    activity_dict = {}
    try:
        with open("activity.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                activity_dict[row["user_id"]] = row
        print(f"  [+] Loaded {len(activity_dict)} activity records")
    except FileNotFoundError:
        print(f"  [!] activity.csv not found, will create new records")
    print()
    
    # Extract primary language for each user
    print("[3/4] Extracting primary languages...")
    print(f"  [*] This will make ~1,200-1,500 API requests")
    print(f"  [*] Estimated time: 15-20 minutes")
    print()
    
    users_complete = []
    failed_users = []
    
    for idx, user in enumerate(users, 1):
        username = user["username"]
        user_id = user["user_id"]
        
        print(f"Processing user {idx}/{len(users)}: {username}")
        
        # Get primary language
        primary_language = get_primary_language(username, headers)
        
        if primary_language:
            print(f"  [+] Primary language: {primary_language}")
        else:
            print(f"  [-] No language data")
        
        # Create complete user record
        user_complete = user.copy()
        user_complete["primary_language"] = primary_language
        users_complete.append(user_complete)
        
        # Progress save every 100 users
        if idx % 100 == 0:
            print(f"\n  [*] Saving progress... ({idx}/{len(users)} completed)")
            with open("users_complete_temp.csv", "w", newline="", encoding="utf-8") as f:
                fieldnames = ["user_id", "username", "location", "created_at", "account_age_years",
                            "profile_url", "public_repos", "followers", "primary_language"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(users_complete)
            print(f"  [+] Progress saved to users_complete_temp.csv")
            print()
    
    print()
    print("[4/4] Creating complete datasets...")
    
    # Save users_complete.csv
    print("  [*] Creating users_complete.csv...")
    with open("users_complete.csv", "w", newline="", encoding="utf-8") as f:
        fieldnames = ["user_id", "username", "location", "created_at", "account_age_years",
                     "profile_url", "public_repos", "followers", "primary_language"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(users_complete)
    print(f"  [+] Saved {len(users_complete)} users to users_complete.csv")
    
    # Create activity_complete.csv
    print("  [*] Creating activity_complete.csv...")
    activity_complete = []
    
    for user in users:
        user_id = user["user_id"]
        username = user["username"]
        
        if user_id in activity_dict:
            # User has activity data
            activity = activity_dict[user_id]
            activity_record = {
                "user_id": user_id,
                "username": username,
                "has_recent_events": "True",
                "repos_starred": activity.get("repos_starred", "0"),
                "recent_push_events": "0",  # Not captured in original extraction
                "commits": activity.get("commits", "0"),
                "prs_merged": activity.get("prs_merged", "0"),
                "activity_date": activity.get("activity_date", "")
            }
        else:
            # User has no recent public events
            activity_record = {
                "user_id": user_id,
                "username": username,
                "has_recent_events": "False",
                "repos_starred": "0",
                "recent_push_events": "0",
                "commits": "0",
                "prs_merged": "0",
                "activity_date": ""
            }
        
        activity_complete.append(activity_record)
    
    with open("activity_complete.csv", "w", newline="", encoding="utf-8") as f:
        fieldnames = ["user_id", "username", "has_recent_events", "repos_starred",
                     "recent_push_events", "commits", "prs_merged", "activity_date"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(activity_complete)
    print(f"  [+] Saved {len(activity_complete)} activity records to activity_complete.csv")
    
    # Clean up temp file
    try:
        os.remove("users_complete_temp.csv")
        print("  [+] Removed temporary file")
    except:
        pass
    
    print()
    print("="*70)
    print("EXTRACTION COMPLETE!")
    print("="*70)
    print()
    print("RESULTS:")
    print(f"  [+] users_complete.csv: {len(users_complete)} users with primary_language")
    print(f"  [+] activity_complete.csv: {len(activity_complete)} users with activity data")
    print()
    
    # Statistics
    users_with_language = sum(1 for u in users_complete if u["primary_language"])
    users_with_activity = sum(1 for a in activity_complete if a["has_recent_events"] == "True")
    
    print("STATISTICS:")
    print(f"  [+] Users with primary language: {users_with_language}/{len(users_complete)}")
    print(f"  [+] Users with recent public events: {users_with_activity}/{len(activity_complete)}")
    print()
    
    print("IMPORTANT NOTES:")
    print("  [*] PRIMARY LANGUAGE: Determined from user's public repositories")
    print("      Rule: Language appearing in most repositories")
    print()
    print("  [*] RECENT COMMIT ACTIVITY LIMITATION:")
    print("      GitHub's /users/{username}/events/public API only returns")
    print("      the ~30 most recent public events. Therefore:")
    print("      - 'commits' = commits from recent PushEvents (limited window)")
    print("      - 'has_recent_events' = whether user had any recent public activity")
    print("      - Many active users may show 0 commits due to API limitation")
    print()
    print("FILES PRESERVED (unchanged):")
    print("  [+] users.csv")
    print("  [+] languages.csv")
    print("  [+] activity.csv")
    print()
    print("="*70)

if __name__ == "__main__":
    main()
