import requests
import sqlite3
import time
import json
import os
import concurrent.futures
import threading

# --- Configuration ---

# !!! IMPORTANT !!!
# You must provide both an Authorization Token and a Perfil ID.
# 1. Login to https://play.cine.ar in your browser.
# 2. Open Developer Tools (F12) -> 'Network' tab.
# 3. Find a request to the '/api/' endpoint (e.g., for a movie).
# 4. In 'Request Headers', find the 'Authorization' header and copy its value.
# 5. In the URL of that same request, find the 'perfil' query parameter and copy its value.

AUTH_TOKEN = os.getenv("CINEAR_AUTH_TOKEN", "")  # "Bearer eyJ..."
PERFIL_ID = os.getenv("CINEAR_PERFIL_ID", "")

API_URL_TEMPLATE = "https://play.cine.ar/api/v1.7/INCAA/prod/{id}?perfil={perfil_id}"
DB_FILE = "movies_shows.db"
START_ID = 1
CONCURRENT_REQUESTS = 2
MAX_ID_TO_SCRAPE = 100000  # Set a reasonable upper limit
READY_FILE = "ready_new.txt"
AUTH_RETRY_LIMIT = 5
AUTH_RETRY_DELAY = 35 # seconds
AUTH_SKIP_HALT_LIMIT = 5

# --- Database Setup ---
def setup_database():
    """Initializes the database and the movies table if they don't exist."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS movies (
        id INTEGER PRIMARY KEY,
        name TEXT,
        synopsis TEXT,
        year INTEGER,
        duration_minutes INTEGER,
        rProme REAL,
        rVotan INTEGER,
        raw_response TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()

def get_last_scraped_id():
    """Finds the last successfully scraped ID from the database."""
    if not os.path.exists(DB_FILE):
        return START_ID - 1
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(id) FROM movies")
    last_id = cursor.fetchone()[0]
    conn.close()
    return last_id if last_id is not None else START_ID - 1

def get_ready_ids():
    """Reads the list of already processed IDs from ready.txt."""
    if not os.path.exists(DB_FILE):
        return set()
    with open(READY_FILE, 'r') as f:
        return {int(line.strip()) for line in f if line.strip()}

def add_id_to_ready_file(movie_id, lock):
    """Appends a successfully processed ID to the ready file in a thread-safe way."""
    with lock:
        with open(READY_FILE, 'a') as f:
            f.write(f"{movie_id}\n")

def save_movie_data(movie_id, data):
    """Saves the scraped movie data to the SQLite database."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()

    name = data.get("tit")
    synopsis = data.get("sino")
    year = data.get("an")
    duration_minutes = data.get("dura")
    raw_response_json = json.dumps(data)
    r_prome = data.get("rProme")
    r_votan = data.get("rVotan")

    try:
        cursor.execute("""
        INSERT INTO movies (id, name, synopsis, year, duration_minutes, rProme, rVotan, raw_response)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (movie_id, name, synopsis, year, duration_minutes, r_prome, r_votan, raw_response_json))
        conn.commit()
        print(f"Successfully saved data for ID {movie_id}: {name}")
    except sqlite3.IntegrityError:
        print(f"Data for ID {movie_id} already exists. Skipping.")
    finally:
        conn.close()

# --- Scraping Worker ---
def scrape_movie(movie_id, headers, ready_ids):
    """Scrapes a single movie ID with retry logic for authorization errors."""
    if movie_id in ready_ids:
        print(f"ID {movie_id} is in ready.txt. Skipping.")
        return "skipped_ready"

    target_url = API_URL_TEMPLATE.format(id=movie_id, perfil_id=PERFIL_ID)
    print(f"Attempting to scrape {target_url}...")
    
    for attempt in range(AUTH_RETRY_LIMIT):
        try:
            response = requests.get(target_url, headers=headers, timeout=15)
            
            if response.status_code == 404:
                print(f"ID {movie_id} not found (404).")
                return "not_found"
            elif response.status_code == 401:
                print(f"Authorization failed (401) for ID {movie_id}. Attempt {attempt + 1}/{AUTH_RETRY_LIMIT}. Retrying in {AUTH_RETRY_DELAY}s...")
                time.sleep(AUTH_RETRY_DELAY)
                continue # Retry
            
            response.raise_for_status()
            movie_data = response.json()
            save_movie_data(movie_id, movie_data)
            return "success"

        except requests.exceptions.RequestException as e:
            print(f"Request failed for ID {movie_id}: {e}")
            return "request_error"
        except json.JSONDecodeError:
            print(f"Failed to decode JSON for ID {movie_id}.")
            return "json_error"

    print(f"Skipping ID {movie_id} after {AUTH_RETRY_LIMIT} failed authorization attempts.")
    return "skipped_auth_error"

# --- Main Scraping Logic ---
def main():
    """Main function to run the scraper."""
    print("--- CINE.AR Scraper (Concurrent with Retry & Tracking) ---")
    
    if not AUTH_TOKEN or "Bearer" not in AUTH_TOKEN or not PERFIL_ID:
        print("ERROR: Please set both AUTH_TOKEN and PERFIL_ID in the script before running.")
        return

    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    setup_database()
    
    last_id = get_last_scraped_id()
    start_id = last_id + 1
    
    ready_ids = get_ready_ids()
    print(f"Loaded {len(ready_ids)} IDs from {READY_FILE} to ignore.")
    
    print(f"Resuming from ID {start_id}...")
    headers = {"Authorization": AUTH_TOKEN}
    ready_file_lock = threading.Lock()

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        future_to_id = {executor.submit(scrape_movie, i, headers, ready_ids): i for i in range(start_id, MAX_ID_TO_SCRAPE)}
        
        consecutive_failures = 0
        skipped_auth_count = 0
        
        for future in concurrent.futures.as_completed(future_to_id):
            movie_id = future_to_id[future]
            result = future.result()
            
            if result == "success":
                consecutive_failures = 0
                add_id_to_ready_file(movie_id, ready_file_lock)
            elif result == "not_found":
                consecutive_failures += 1
                add_id_to_ready_file(movie_id, ready_file_lock)
            elif result == "skipped_auth_error":
                skipped_auth_count += 1
            elif result in ["request_error", "json_error"]:
                consecutive_failures += 1
            
            if skipped_auth_count >= AUTH_SKIP_HALT_LIMIT:
                print(f"\nHALTING: Skipped {skipped_auth_count} IDs due to persistent authorization failures.")
                for f in future_to_id:
                    f.cancel()
                break

            if consecutive_failures >= 1000:
                 print(f"Stopping scraper due to {consecutive_failures} consecutive failures.")
                 break

    print(f"\nScraping finished.")

if __name__ == "__main__":
    main()
