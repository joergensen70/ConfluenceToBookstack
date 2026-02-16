import base64
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
TARGET_TITLES = [
    "Volkszähler",
    "Anleitungsartikel",
    "Web Cam",
    "RS485/Modbus Stromzähler an NodeRed",
    "Outlook365 winmail.dat Problem",
    "Moved to bookstack",
    "Optional Hostename....",
    "Putty",
    "CN Migration....",
]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    load_dotenv(ROOT / ".env")

    base_url = os.environ["CONFLUENCE_BASE_URL"].rstrip("/")
    email = os.environ["CONFLUENCE_EMAIL"]
    token = os.environ["CONFLUENCE_API_TOKEN"]

    auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
    session = requests.Session()
    session.headers.update({"Authorization": f"Basic {auth}", "Accept": "application/json"})

    # Full page set in CN for hierarchy check
    pages = []
    start = 0
    limit = 50
    seen = set()

    for _ in range(2000):
        params = {
            "cql": 'space="CN" and type=page',
            "expand": "ancestors",
            "limit": limit,
            "start": start,
        }
        r = session.get(f"{base_url}/wiki/rest/api/content/search", params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        batch = data.get("results", [])
        if not batch:
            break
        new_count = 0
        for item in batch:
            pid = str(item.get("id", ""))
            if pid in seen:
                continue
            seen.add(pid)
            pages.append(item)
            new_count += 1
        if new_count == 0:
            break
        if len(batch) < limit:
            break
        start += len(batch)

    page_map = {str(p["id"]): p for p in pages}

    print(f"CN_TOTAL={len(pages)}")

    roots = []
    for p in pages:
        parent = None
        for anc in reversed(p.get("ancestors", []) or []):
            aid = str(anc.get("id", ""))
            if aid in page_map:
                parent = aid
                break
        if parent is None:
            roots.append(p)

    print(f"CN_TOP_LEVEL={len(roots)}")
    for r in sorted(roots, key=lambda x: (x.get("title") or "").lower()):
        print(f"ROOT::{r.get('id')}::{r.get('title','')}")

    print("\nCHECK_TITLES")
    for title in TARGET_TITLES:
        cql = f'space="CN" and type=page and title="{title}"'
        r = session.get(
            f"{base_url}/wiki/rest/api/content/search",
            params={"cql": cql, "limit": 50, "expand": "ancestors"},
            timeout=60,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        print(f"TITLE::{title}::HITS={len(results)}")
        for item in results:
            ancestors = item.get("ancestors", []) or []
            if not ancestors:
                chain = "<ROOT>"
            else:
                titles = []
                for anc in ancestors:
                    aid = str(anc.get("id", ""))
                    a_title = page_map.get(aid, {}).get("title") or anc.get("title") or f"id:{aid}"
                    titles.append(a_title)
                chain = " > ".join(titles)
            print(f"  - PAGE::{item.get('id')}::{item.get('title','')}::ANCESTORS={chain}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
