import requests
import time
import csv
import os
import json
from dotenv import load_dotenv
import urllib.parse

load_dotenv()

BASE_URL = "https://cortex.nyphil.org"
OAUTH_URL = f"{BASE_URL}/oauth2/token"
CLIENT_ID = os.getenv("CORTEX_CLIENT_ID")
CLIENT_SECRET = os.getenv("CORTEX_CLIENT_SECRET")
USERNAME = os.getenv("CORTEX_USERNAME")
PASSWORD = os.getenv("CORTEX_PASSWORD")
DRY_RUN = False
LOG_FILE = "reorder_log.csv"
PROCESSED_FILE = "processed_pages.txt"
PROCESSED_FOLDERS_FILE = "processed_folders.txt"
ALREADY_ORDERED_FILE = "already_ordered_folders.txt"
CACHED_PARENTS_FILE = "cached_parent_folders.json"

TOKEN = None
HEADERS = {}
COOKIE_TOKEN = None

SUBTYPES = ["Concert Program", "Score", "Part", "Business Document", "Press Clippings"]

def get_token():
    global TOKEN, HEADERS, COOKIE_TOKEN
    print("🔑 Getting new tokens...")
    url = "https://cortex.nyphil.org/webapi/security/oauth2/token_48I_v1"
    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    headers = {
        "Content-Type": "application/json",
        "accept": "application/json"
    }
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    TOKEN = response.json()["access_token"]
    HEADERS = {
        "Authorization": f"Bearer {TOKEN}",
        "accept": "application/json",
        "content-type": "application/json"
    }

    print("🔐 Getting cookie token...")
    auth_url = f"{BASE_URL}/API/Authentication/v1.0/Login"
    params = {
        "Login": USERNAME,
        "Password": PASSWORD,
        "format": "json"
    }
    response = requests.post(auth_url, params=params)
    response.raise_for_status()
    if response.json()['APIResponse']['Code'] == 'SUCCESS':
        COOKIE_TOKEN = response.json()['APIResponse']['Token']
        print("✅ Token refreshed successfully")
    else:
        print("❌ Authentication failed")
        COOKIE_TOKEN = ''

def refresh_token_if_needed(response):
    if response.status_code == 401:
        print("🔁 Refreshing token due to 401 error...")
        get_token()
        return True
    return False

def log_action(parent_uid, step, page_id, filename, status, http_code="", error=""):
    print(f"📄 {step}: {page_id or 'N/A'} ({filename or 'N/A'}) → {status}")
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Parent UID", "Step", "Page ID", "Original FileName", "Status", "HTTP Code", "Error"])
        writer.writerow({
            "Parent UID": parent_uid,
            "Step": step,
            "Page ID": page_id,
            "Original FileName": filename,
            "Status": status,
            "HTTP Code": http_code,
            "Error": error
        })
    if status == "Success" and page_id:
        with open(PROCESSED_FILE, "a") as pf:
            pf.write(page_id + "\n")

def fetch_pages(parent_uid):
    print(f"📅 Fetching pages for folder {parent_uid}...")
    pages = []
    page_number = 1
    while True:
        params = {
            "query": f"ParentFolderIdentifier:{parent_uid} AND DocSubType:Page",
            "fields": "CoreField.Identifier,CoreField.OriginalFileName",
            "format": "json",
            "pagenumber": page_number,
            "countperpage": 100,
            "sort": "manual order",
            "token": COOKIE_TOKEN
        }
        resp = requests.get(f"{BASE_URL}/API/search/v3.0/search", params=params)
        if refresh_token_if_needed(resp):
            params["token"] = COOKIE_TOKEN
            resp = requests.get(f"{BASE_URL}/API/search/v3.0/search", params=params)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("APIResponse", {}).get("Items", [])
        if not items:
            break
        pages.extend(items)
        page_number += 1
    return pages

def batch_unparent(pages, parent_uid):
    print(f"🧹 Unparenting pages from {parent_uid}...")
    record_ids = [page["CoreField.Identifier"] for page in pages if page["CoreField.Identifier"] not in processed_pages]
    if DRY_RUN:
        for uid in record_ids:
            log_action(parent_uid, "Unparent", uid, "", "Dry Run")
        return
    if not record_ids:
        return
    url = f"{BASE_URL}/webapi/objectmanagement/multiobjectstools/batchedit/batcheditfields_4FQ_v1"
    payload = {
        "documents": record_ids,
        "fieldAssignments": [
            {
                "field": "CoreField.Parent-folder",
                "value": "",
                "batchsettings": {"batchOption": "None"}
            }
        ],
        "ignoreNotEditableDocuments": True,
        "ignoreInvalidDocuments": True
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if refresh_token_if_needed(response):
        response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    for uid in record_ids:
        log_action(parent_uid, "Unparent", uid, "", "Success", response.status_code)
    time.sleep(0.3)

def assign_parent(page_id, filename, parent_uid, parent_record_id):
    print(f"🔗 Reparenting page {page_id} ({filename})")
    if page_id in processed_pages:
        return
    if DRY_RUN:
        log_action(parent_uid, "Reparent", page_id, filename, "Dry Run")
        return
    url = f"{BASE_URL}/API/DataTable/v2.2/Documents.Image.Page:Update"
    params = {
        "CoreField.Identifier": page_id,
        "CoreField.Parent-folder:": parent_record_id,
        "token": COOKIE_TOKEN
    }
    response = requests.post(url, params=params)
    if refresh_token_if_needed(response):
        params["token"] = COOKIE_TOKEN
        response = requests.post(url, params=params)
    response.raise_for_status()
    log_action(parent_uid, "Reparent", page_id, filename, "Success", response.status_code)
    time.sleep(0.3)

def process_folder(parent_uid, parent_record_id):
    print(f"🔍 Processing folder {parent_uid}...")
    if os.path.exists(PROCESSED_FOLDERS_FILE):
        with open(PROCESSED_FOLDERS_FILE, "r") as f:
            if parent_uid in {line.strip() for line in f}:
                print(f"⏭️ Skipping already processed folder {parent_uid}")
                return

    cache_file = f"parent_child_cache_{parent_uid}.json"
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            pages = json.load(f)
    else:
        pages = fetch_pages(parent_uid)
        with open(cache_file, "w") as f:
            json.dump(pages, f, indent=2)

    if not pages:
        print(f"⚠️ No pages found for {parent_uid}")
        return
    filenames = [p.get("CoreField.OriginalFileName", "") for p in pages]
    if filenames == sorted(filenames):
        print(f"✅ {parent_uid}: already in correct order")
        with open(ALREADY_ORDERED_FILE, "a") as f:
            f.write(parent_uid + "\n")
        os.remove(cache_file)
        return
    print(f"📑 Reordering {len(pages)} pages...")
    pages_sorted = sorted(pages, key=lambda x: x.get("CoreField.OriginalFileName", ""))
    batch_unparent(pages_sorted, parent_uid)
    for page in pages_sorted:
        assign_parent(page["CoreField.Identifier"], page.get("CoreField.OriginalFileName", ""), parent_uid, parent_record_id)
    with open(PROCESSED_FOLDERS_FILE, "a") as f:
        f.write(parent_uid + "\n")
    os.remove(cache_file)

def get_all_parent_folders():
    print("🔎 Fetching all parent folders by subtype...")
    if os.path.exists(CACHED_PARENTS_FILE):
        with open(CACHED_PARENTS_FILE, "r") as f:
            return json.load(f)

    all_parents = []
    for subtype in SUBTYPES:
        print(f"📂 Subtype: {subtype}")
        page = 1
        while True:
            query = f"DocSubType:{subtype}"
            query_encoded = urllib.parse.quote(query)
            url = (
                f"{BASE_URL}/API/search/v3.0/search?query={query_encoded}"
                f"&fields=CoreField.Unique-Identifier,RecordID,ChildCount&countperpage=300&format=json&pagenumber={page}"
            )
            resp = requests.get(url, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("APIResponse", {}).get("Items", [])
            if not items:
                break
            for item in items:
                uid = item.get("CoreField.Unique-Identifier")
                record_id = item.get("RecordID")
                child_count = int(item.get("ChildCount", 0))
                if uid and record_id and child_count > 0:
                    all_parents.append((uid, record_id))
            if "NextPage" not in data["APIResponse"].get("GlobalInfo", {}):
                break
            page += 1
            time.sleep(0.3)

    with open(CACHED_PARENTS_FILE, "w") as f:
        json.dump(all_parents, f, indent=2)
    return all_parents

def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def main():
    print("🚀 Starting reorder script...")
    get_token()
    global processed_pages
    processed_pages = load_processed()
    all_folders = get_all_parent_folders()
    for folder_uid, record_id in all_folders:
        print(f"\n🔄 Processing folder: {folder_uid}")
        process_folder(folder_uid, record_id)
    print("\n✅ Reordering complete.")

if __name__ == "__main__":
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Parent UID", "Step", "Page ID", "Original FileName", "Status", "HTTP Code", "Error"])
        writer.writeheader()
    main()
