import base64
import os
from pathlib import Path
import requests

root = Path(__file__).resolve().parent
for line in (root / ".env").read_text(encoding="utf-8").splitlines():
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k,v=line.split('=',1)
    if k.strip() not in os.environ:
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

base = os.environ['CONFLUENCE_BASE_URL'].rstrip('/')
email = os.environ['CONFLUENCE_EMAIL']
token = os.environ['CONFLUENCE_API_TOKEN']
auth = base64.b64encode(f"{email}:{token}".encode()).decode('ascii')

s = requests.Session()
s.headers.update({'Authorization': f'Basic {auth}', 'Accept':'application/json'})

for st in [0, 50, 100, 150]:
    params = {
        'cql': 'space="CN" and type=page',
        'expand': 'ancestors',
        'limit': 50,
        'start': st,
    }
    r = s.get(f"{base}/wiki/rest/api/content/search", params=params, timeout=60)
    r.raise_for_status()
    d = r.json()
    results = d.get('results', [])
    next_link = d.get('_links', {}).get('next')
    print(f"START={st} COUNT={len(results)} NEXT={next_link}")
    if results:
        print(f"  FIRST={results[0].get('id')}::{results[0].get('title','')}")
        print(f"  LAST={results[-1].get('id')}::{results[-1].get('title','')}")
