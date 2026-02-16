import argparse
import os
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
    parser.add_argument("--needle", required=True)
    args = parser.parse_args()

    load_dotenv(Path(".env"))
    cfg = load_config_from_env()
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    pages = bs._request("GET", "/api/pages?count=500")
    hits = []
    for page in pages.get("data", []):
        if args.needle.lower() in (page.get("name", "").lower()):
            hits.append(page)

    print(f"HITS={len(hits)}")
    for item in hits:
        print(f"PAGE_ID={item.get('id')} NAME={item.get('name')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
