import base64
import os
from pathlib import Path

import requests

root = Path(__file__).resolve().parent
for line in (root / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if key and key not in os.environ:
        os.environ[key] = value

base_url = os.environ["CONFLUENCE_BASE_URL"].rstrip("/")
email = os.environ["CONFLUENCE_EMAIL"]
token = os.environ["CONFLUENCE_API_TOKEN"]

auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
session = requests.Session()
session.headers.update({"Authorization": f"Basic {auth}", "Accept": "application/json"})

start = 0
limit = 200
all_spaces = []
for _ in range(50):
    response = session.get(f"{base_url}/wiki/rest/api/space", params={"limit": limit, "start": start}, timeout=60)
    response.raise_for_status()
    data = response.json()
    batch = data.get("results", [])
    if not batch:
        break
    all_spaces.extend(batch)
    if len(batch) < limit:
        break
    start += len(batch)

print(f"SPACE_COUNT={len(all_spaces)}")
for sp in all_spaces:
    key = sp.get("key", "")
    name = sp.get("name", "")
    print(f"SPACE={key}::{name}")
