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
    load_dotenv(Path(".env"))
    cfg = load_config_from_env()
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    page = bs._request("GET", "/api/pages/220")

    base = cfg.bookstack_base_url.rstrip("/")
    book_slug = page.get("book_slug")
    slug = page.get("slug")

    if book_slug and slug:
        direct = f"{base}/books/{book_slug}/page/{slug}"
    elif page.get("url"):
        direct = f"{base}{page['url']}"
    else:
        direct = f"{base}/books"

    print(f"DIRECT_LINK={direct}")
    print(f"PAGE_NAME={page.get('name','')}")
    print(f"PAGE_ID={page.get('id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
