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

    try:
        books = bs._request("GET", "/api/books?count=1")
        print("BOOKS_API_OK")
        print(f"TOTAL={books.get('total')}")
        return 0
    except Exception as exc:
        print("BOOKS_API_FAIL")
        print(type(exc).__name__)
        print(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
