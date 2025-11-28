import requests
import json
import sys

# SN4 = SE4 (Malmö). Change to SN3 (Stockholm) if needed.
area = "SN4"
start = "2025-08-01"
end = "2025-08-02"

url = f"https://www.vattenfall.se/api/price/spot/pricearea/{start}/{end}/{area}"

print(f"Fetching: {url}")

try:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()

    data = resp.json()
    print(f"Status: {resp.status_code}")
    print(f"Records found: {len(data)}")

    if data:
        print("First record sample:")
        print(json.dumps(data[0], indent=2))
        print("Last record sample:")
        print(json.dumps(data[-1], indent=2))

except Exception as e:
    print(f"Error: {e}")
