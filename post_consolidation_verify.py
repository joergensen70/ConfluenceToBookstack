import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, load_config_from_env


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " und ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()

    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)

    books = bs._request("GET", "/api/books?count=500").get("data", [])
    pages = bs._request("GET", "/api/pages?count=500").get("data", [])
    chapters = bs._request("GET", "/api/chapters?count=500").get("data", [])

    cn_books = []
    for b in books:
        n = norm(b.get("name", ""))
        slug = (b.get("slug") or "").lower()
        if ("confluence" in n and "computer" in n and "netzwerk" in n) or ("confluence-computer-netzwerk" in slug):
            cn_books.append(b)

    print(f"CN_BOOKS={len(cn_books)}")
    for b in cn_books:
        bid = int(b["id"])
        pcount = sum(1 for p in pages if int(p.get("book_id", -1)) == bid)
        ccount = sum(1 for c in chapters if int(c.get("book_id", -1)) == bid)
        print(f"BOOK={bid}::{b.get('name')}::pages={pcount}::chapters={ccount}")

    if not cn_books:
        return 0

    target = cn_books[0]
    target_id = int(target["id"])
    target_pages = [p for p in pages if int(p.get("book_id", -1)) == target_id]

    by_name = defaultdict(list)
    for p in target_pages:
        by_name[norm(p.get("name", ""))].append(p)
    dup_groups = {k: v for k, v in by_name.items() if len(v) > 1}

    print(f"TARGET_BOOK_ID={target_id}")
    print(f"TARGET_PAGES={len(target_pages)}")
    print(f"DUPLICATE_NAME_GROUPS={len(dup_groups)}")
    for _, group in list(dup_groups.items())[:20]:
        print("DUP_NAME=" + (group[0].get("name") or ""))

    conf_pages = conf.list_pages_in_space(cfg.confluence_space_key)
    conf_titles = [p.get("title", "") for p in conf_pages]
    bs_norm = set(norm(p.get("name", "")) for p in target_pages)
    missing_exact = [t for t in conf_titles if norm(t) not in bs_norm]

    print(f"CONF_TOTAL={len(conf_titles)}")
    print(f"MISSING_EXACT_TITLE_COUNT={len(missing_exact)}")
    for t in missing_exact[:30]:
        print("MISSING=" + t)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
