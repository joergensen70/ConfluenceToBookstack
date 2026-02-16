import argparse
import os
import re
from pathlib import Path

from confluence_to_bookstack_migration import BookStackClient, load_config_from_env


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-id", required=True, type=int)
    args = parser.parse_args()

    load_dotenv(Path(".env"))
    cfg = load_config_from_env()
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    page = bs._request("GET", f"/api/pages/{args.page_id}")
    html = page.get("raw_html") or page.get("html") or ""
    img_count = len(re.findall(r"<img\\b", html, flags=re.IGNORECASE))
    has_bookstack_img = cfg.bookstack_base_url.rstrip("/") in html

    print(f"PAGE_ID={args.page_id}")
    print(f"NAME={page.get('name','')}")
    print(f"IMG_TAGS={img_count}")
    print(f"HAS_BOOKSTACK_IMG_URL={has_bookstack_img}")
    print(f"URL={page.get('url','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
