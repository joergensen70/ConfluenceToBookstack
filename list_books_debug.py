import os
import re
import unicodedata
from pathlib import Path

from confluence_to_bookstack_migration import BookStackClient, load_config_from_env


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " und ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    books = bs._request("GET", "/api/books?count=500").get("data", [])
    print(f"BOOK_TOTAL={len(books)}")
    for b in books:
        name = b.get("name", "")
        if "confluence" in name.lower() or "computer" in name.lower() or "netzwerk" in name.lower():
            print(f"BOOK={b.get('id')}::{name}::{b.get('slug')}::NORM={normalize(name)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
