import os
from pathlib import Path

import requests

from confluence_to_bookstack_migration import BookStackClient, load_config_from_env


TEST_NEEDLE = "CN Migration Testseite mit Bild 2026-02-16 14:33:33"
CONFLUENCE_TEST_PAGE_ID = "208633859"


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def delete_bookstack_test_pages() -> None:
    cfg = load_config_from_env()
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    pages = bs._request("GET", "/api/pages?count=500")
    hits = [p for p in pages.get("data", []) if TEST_NEEDLE.lower() in (p.get("name", "").lower())]

    print(f"BOOKSTACK_HITS={len(hits)}")
    for page in hits:
        page_id = page.get("id")
        page_name = page.get("name", "")
        response = bs.session.delete(f"{cfg.bookstack_base_url.rstrip('/')}/api/pages/{page_id}", timeout=60)
        if response.status_code in (200, 204):
            print(f"BOOKSTACK_DELETED={page_id}::{page_name}")
        else:
            print(f"BOOKSTACK_DELETE_FAILED={page_id}::{response.status_code}::{response.text[:160]}")


def delete_confluence_test_page() -> None:
    cfg = load_config_from_env()

    session = requests.Session()
    session.auth = (cfg.confluence_email, cfg.confluence_api_token)
    session.headers.update({"Accept": "application/json"})

    delete_url = f"{cfg.confluence_base_url.rstrip('/')}/wiki/rest/api/content/{CONFLUENCE_TEST_PAGE_ID}"
    response = session.delete(delete_url, params={"status": "current"}, timeout=60)

    if response.status_code in (200, 202, 204):
        print(f"CONFLUENCE_DELETED={CONFLUENCE_TEST_PAGE_ID}")
    else:
        print(f"CONFLUENCE_DELETE_FAILED={response.status_code}::{response.text[:200]}")


def main() -> int:
    load_dotenv(Path(".env"))
    delete_bookstack_test_pages()
    delete_confluence_test_page()
    print("CLEANUP_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
