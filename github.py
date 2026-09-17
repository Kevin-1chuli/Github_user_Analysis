import os
import requests
from dotenv import load_dotenv
from datetime import datetime
import time
import csv

load_dotenv()

token = os.getenv("github_token")

if not token:
    raise ValueError("Github token was not found in the .env file")

#  function for retry logic
def make_request_with_retry(url, headers, params=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            # Rate-limit management
            if response.status_code == 403:
                if 'X-RateLimit-Remaining' in response.headers and response.headers['X-RateLimit-Remaining'] == '0':
                    reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                    wait_time = reset_time - int(time.time())
                    if wait_time > 0:
                        print(f"Rate limit exceeded. Waiting {wait_time} seconds...")
                        time.sleep(wait_time + 1)
                        continue
            
            return response
            
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries - 1:
                print(f"Request failed (attempt {attempt + 1}/{max_retries}), retrying...")
                time.sleep(2)
            else:
                print(f"Request failed after {max_retries} attempts")
                return None
    
    return None

url = "https://api.github.com/users"

# Request headers
headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {token}"
}

# Collect all users from pagination
all_users = []

for page in range(1, 11):
    params = {
        "per_page":100,
        "page": page
    }
    response = make_request_with_retry(url, headers, params)

    if response is None:
        print(f"Failed to get users on page {page}")
        continue

    print("Status code: ", response.status_code)

    if response.status_code != 200:
        print("Failed to get users!")
        print(response.text)
        continue

    users = response.json()
    all_users.extend(users)
    print(f"Page {page}/10 - {len(all_users)} users collected\n")

#Getting detailed information for each user
detailed_users = []
# NEW: Collections for Star Schema staging files
users_dim = []
all_languages = set()
activity_records = []

total_users = len(all_users)

for idx, user in enumerate(all_users, 1):
    username = user["login"]
    print(f"Processing user {idx}/{total_users}: {username}")

    user_url = f"https://api.github.com/users/{username}"
    user_response = make_request_with_retry(user_url, headers)

    if user_response is None:
        print(f"  ! Could not get details: {username} (request failed)")
        continue

    if user_response.status_code != 200:
        print(f"  ! Could not get details for {username} (status: {user_response.status_code})")
        continue
    
    if user_response.status_code == 200:
        user_data = user_response.json()
        
        #  Initialize record dictionary
        user_record = {
            "user_id": user_data.get("id", "N/A"),
            "username": user_data.get("login", "N/A"),
            "profile_url": user_data.get("html_url", "N/A"),
            "public_repos": user_data.get("public_repos", "N/A"),
            "followers": user_data.get("followers", "N/A"),
            "created_at": "N/A",
            "account_age_years": "N/A",
            "primary_language": "N/A",
            "recent_push_events": "N/A",
            "last_activity_date": "N/A",
            "location": user_data.get("location", "N/A"),  # NEW: for dim_user
            "repos_starred": 0, 
            "prs_merged": 0,  
            "commits": 0  
        }
        
        # Account Age
        created_at = user_data.get("created_at", "N/A")
        user_record["created_at"] = created_at
        if created_at != "N/A":
            try:
                created_date = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
                current_date = datetime.now()
                account_age_years = round((current_date - created_date).days / 365.25, 2)
                user_record["account_age_years"] = account_age_years
            except Exception as e:
                pass  # Silently handle calculation errors
        
        # Programming Languages - with pagination for complete repository coverage
        repos_url = f"https://api.github.com/users/{username}/repos"
        languages = {}
        repos_page = 1
        
        while True:
            repos_params = {"per_page": 100, "page": repos_page}
            repos_response = make_request_with_retry(repos_url, headers, repos_params)
            
            if not repos_response or repos_response.status_code != 200:
                break
            
            repos_data = repos_response.json()
            if not repos_data:
                break
            
            for repo in repos_data:
                language = repo.get("language")
                if language:
                    languages[language] = languages.get(language, 0) + 1
                    all_languages.add(language)
            
            repos_page += 1
            
            if len(repos_data) < 100:
                break
        
        if languages:
            primary_language = max(languages, key=languages.get)
            user_record["primary_language"] = primary_language
        
        #  Starred repositories for activity_fact
        starred_url = f"https://api.github.com/users/{username}/starred"
        starred_count = 0
        starred_page = 1
        
        while True:
            starred_params = {"per_page": 100, "page": starred_page}
            starred_response = make_request_with_retry(starred_url, headers, starred_params)
            
            if not starred_response or starred_response.status_code != 200:
                break
            
            starred_data = starred_response.json()
            if not starred_data:
                break
            
            starred_count += len(starred_data)
            starred_page += 1
            
            if len(starred_data) < 100:
                break
        
        user_record["repos_starred"] = starred_count
        
        # Recent Commit / Activity -  improved with commit counts and PR tracking
        events_url = f"https://api.github.com/users/{username}/events/public"
        events_response = make_request_with_retry(events_url, headers)
        
        if events_response and events_response.status_code == 200:
            events_data = events_response.json()
            
            # Count PushEvents
            recent_push_events = sum(1 for event in events_data if event.get("type") == "PushEvent")
            user_record["recent_push_events"] = recent_push_events
            
            # Count actual commits from PushEvent payloads
            commits_count = 0
            for event in events_data:
                if event.get("type") == "PushEvent":
                    payload = event.get("payload", {})
                    commits = payload.get("commits", [])
                    commits_count += len(commits)
            user_record["commits"] = commits_count
            
            # Count merged PRs from PullRequestEvent
            prs_merged = 0
            for event in events_data:
                if event.get("type") == "PullRequestEvent":
                    payload = event.get("payload", {})
                    action = payload.get("action")
                    pull_request = payload.get("pull_request", {})
                    if action == "closed" and pull_request.get("merged"):
                        prs_merged += 1
            user_record["prs_merged"] = prs_merged
            
            # Get last activity date
            if events_data:
                last_activity_date = events_data[0].get("created_at", "N/A")
                user_record["last_activity_date"] = last_activity_date
                
                # Create activity_fact record
                activity_record = {
                    "user_id": user_data.get("id", "N/A"),
                    "username": user_data.get("login", "N/A"),
                    "repos_starred": starred_count,
                    "prs_merged": prs_merged,
                    "commits": commits_count,
                    "activity_date": last_activity_date
                }
                activity_records.append(activity_record)
        
        # Store user record
        detailed_users.append(user_record)
        
        # NEW: Create dim_user record
        user_dim_record = {
            "user_id": user_data.get("id", "N/A"),
            "username": user_data.get("login", "N/A"),
            "location": user_data.get("location", "N/A"),
            "created_at": created_at,
            "account_age_years": user_record["account_age_years"],
            "profile_url": user_data.get("html_url", "N/A"),
            "public_repos": user_data.get("public_repos", "N/A"),
            "followers": user_data.get("followers", "N/A")
        }
        users_dim.append(user_dim_record)
        
        # Progress summary every 100 users
        if idx % 100 == 0:
            print(f"  - {idx}/{total_users} users processed")
        
    else:
        print(f"  ! Could not get details for {username} (status: {user_response.status_code})")

# Save to CSV files
print(f"\n{'='*60}")
print("SAVING DATA TO CSV FILES")
print(f"{'='*60}\n")

# 1. users.csv for dim_user
print(f"Creating users.csv...")
with open("users.csv", "w", newline="", encoding="utf-8") as csvfile:
    fieldnames = ["user_id", "username", "location", "created_at", "account_age_years",
                  "profile_url", "public_repos", "followers"]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(users_dim)

# 2. languages.csv for dim_language
print(f"Creating languages.csv...")
with open("languages.csv", "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["language"])
    for language in sorted(all_languages):
        writer.writerow([language])

# 3. activity.csv for activity_fact
print(f"Creating activity.csv...")
with open("activity.csv", "w", newline="", encoding="utf-8") as csvfile:
    fieldnames = ["user_id", "username", "repos_starred", "prs_merged", "commits", "activity_date"]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(activity_records)

print(f"\n{'='*60}")
print("EXTRACTION COMPLETE!")
print(f"{'='*60}")
print(f"[+] Users extracted: {len(users_dim)}")
print(f"[+] Distinct languages: {len(all_languages)}")
print(f"[+] Activity records: {len(activity_records)}")
print(f"\nCSV files created:")
print(f"  * users.csv")
print(f"  * languages.csv")
print(f"  * activity.csv")
print(f"{'='*60}")