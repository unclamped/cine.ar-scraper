
import json
import sqlite3

def get_all_keys(json_obj, keys):
    if isinstance(json_obj, dict):
        for key, value in json_obj.items():
            keys.add(key)
            get_all_keys(value, keys)
    elif isinstance(json_obj, list):
        for item in json_obj:
            get_all_keys(item, keys)

def main():
    conn = sqlite3.connect('movies.db')
    cursor = conn.cursor()
    cursor.execute("SELECT raw_response FROM movies")
    rows = cursor.fetchall()
    conn.close()

    all_keys = set()
    for row in rows:
        try:
            json_data = json.loads(row[0])
            get_all_keys(json_data, all_keys)
        except json.JSONDecodeError:
            # Handle cases where the raw_response is not a valid JSON
            pass

    for key in sorted(list(all_keys)):
        print(key)

if __name__ == "__main__":
    main()
