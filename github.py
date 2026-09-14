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

# ADDED: Helper function for retry logic
def make_request_with_retry(url, headers, params=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            # ADDED: Rate-limit management
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

# ADDED: Collect all users from pagination
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
total_users = len(all_users)

for idx, user in enumerate(all_users, 1):
    username = user["login"]
    print(f"Processing user {idx}/{total_users}: {username}")

    user_url = f"https://api.github.com/users/{username}"
    user_response = make_request_with_retry(user_url, headers)

    if user_response is None:
        print(f"Could not get details: {username}")
        continue

    print("Status_code:", user_response.status_code)
    
    if user_response.status_code == 200:
        user_data = user_response.json()
        
        # ADDED: Initialize record dictionary
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
            "last_activity_date": "N/A"
        }
        
        print("Username:", user_data["login"])
        print("User ID:", user_data["id"])
        print("Profile url:", user_data["html_url"])
        print("Public repositories:", user_data["public_repos"])
        print("Followers:", user_data["followers"])
        
        # Account Age
        created_at = user_data.get("created_at", "N/A")
        print("Created at:", created_at)
        user_record["created_at"] = created_at
        if created_at != "N/A":
            try:
                created_date = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
                current_date = datetime.now()
                account_age_years = round((current_date - created_date).days / 365.25, 2)
                print("Account age (years):", account_age_years)
                user_record["account_age_years"] = account_age_years
            except Exception as e:
                print("Account age (years): Could not calculate")
        
        # Programming Languages
        repos_url = f"https://api.github.com/users/{username}/repos"
        repos_response = make_request_with_retry(repos_url, headers)
        
        if repos_response and repos_response.status_code == 200:
            repos_data = repos_response.json()
            languages = {}
            for repo in repos_data:
                language = repo.get("language")
                if language:
                    languages[language] = languages.get(language, 0) + 1
            
            if languages:
                primary_language = max(languages, key=languages.get)
                print("Primary language:", primary_language)
                user_record["primary_language"] = primary_language
            else:
                print("Primary language: N/A")
        else:
            print("Primary language: Could not fetch repositories")
        
        # Recent Commit / Activity
        events_url = f"https://api.github.com/users/{username}/events/public"
        events_response = make_request_with_retry(events_url, headers)
        
        if events_response and events_response.status_code == 200:
            events_data = events_response.json()
            recent_push_events = sum(1 for event in events_data if event.get("type") == "PushEvent")
            print("Recent push events:", recent_push_events)
            user_record["recent_push_events"] = recent_push_events
            
            if events_data:
                last_activity_date = events_data[0].get("created_at", "N/A")
                print("Last activity date:", last_activity_date)
                user_record["last_activity_date"] = last_activity_date
            else:
                print("Last activity date: N/A")
        else:
            print("Recent push events: Could not fetch events")
            print("Last activity date: Could not fetch events")
        
        # ADDED: Store user record
        detailed_users.append(user_record)
        
        print()
    else:
        print("Could not get details:", username)

# ADDED: Save to CSV
print(f"\nSaving {len(detailed_users)} user records to github_users.csv...")
with open("github_users.csv", "w", newline="", encoding="utf-8") as csvfile:
    fieldnames = ["user_id", "username", "profile_url", "public_repos", "followers", 
                  "created_at", "account_age_years", "primary_language", 
                  "recent_push_events", "last_activity_date"]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(detailed_users)

print(f"Extraction complete! {len(detailed_users)} users saved to github_users.csv")