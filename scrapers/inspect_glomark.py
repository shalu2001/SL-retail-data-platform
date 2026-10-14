import json
import requests

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
})

# Test the failing ID
resp = session.post("https://glomark.lk/product-page/variation-detail/15428", timeout=20)
print(f"Status Code: {resp.status_code}")
print(json.dumps(resp.json(), indent=2))