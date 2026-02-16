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


def norm(s: str) -> str:
    s = (s or "").lower()
    return s


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    books = bs._request("GET", "/api/books?count=500").get("data", [])
    target = None
    for b in books:
        name = (b.get("name") or "").lower()
        slug = (b.get("slug") or "").lower()
        if ("confluence" in name and "computer" in name and "netzwerk" in name) or ("confluence-computer-netzwerk" in slug):
            target = b
            break

    if not target:
        print("TARGET_BOOK=NONE")
        return 0

    target_id = int(target["id"])
    chapters = bs._request("GET", "/api/chapters?count=500").get("data", [])
    target_ch = [c for c in chapters if int(c.get("book_id", -1)) == target_id]

    print(f"TARGET_BOOK_ID={target_id}")
    print(f"TARGET_BOOK_NAME={target.get('name')}")
    print(f"CHAPTER_COUNT={len(target_ch)}")
    for ch in target_ch:
        print(f"CHAPTER={ch.get('id')}::{ch.get('name')}::priority={ch.get('priority')}")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
