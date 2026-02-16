import os
import re
from datetime import datetime
from pathlib import Path

from confluence_to_bookstack_migration import (
    BookStackClient,
    ConfluenceClient,
    Migrator,
    load_config_from_env,
)


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()


def main() -> int:
    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    migrator = Migrator(cfg, dry_run=False)

    pages = conf.list_pages_in_space(cfg.confluence_space_key)
    candidate = None
    candidate_rendered_html = ""
    candidate_img_refs = 0

    img_src_pattern = re.compile(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', flags=re.IGNORECASE)

    for page in pages:
        view_html = page.get("body", {}).get("view", {}).get("value", "")
        storage_html = page.get("body", {}).get("storage", {}).get("value", "")
        if "<ac:image" not in storage_html.lower() and "<img" not in storage_html.lower():
            continue

        if view_html:
            rendered_html = view_html
        else:
            try:
                rendered_html = conf.convert_storage_to_view(storage_html)
            except Exception:
                rendered_html = storage_html

        rendered_html = migrator._normalize_html_links(rendered_html)
        img_refs = len(img_src_pattern.findall(rendered_html))
        if img_refs > 0:
            candidate = page
            candidate_rendered_html = rendered_html
            candidate_img_refs = img_refs
            break

    if candidate is None:
        print("TEST_FAIL: Keine Seite mit Bildern im Space gefunden.")
        return 2

    conf_page_id = candidate.get("id")
    conf_title = candidate.get("title", "Untitled")
    rendered_html = candidate_rendered_html

    book_name = "Confluence Image Migration Test"
    book = bs.find_book_by_name(book_name)
    if not book:
        book = bs.create_book(book_name, description="Testbuch für Einzelseiten-Migration mit Bildern")

    page_name = f"TEST {datetime.now().strftime('%Y-%m-%d %H:%M')} - {conf_title}"
    page = bs.create_page(page_name, rendered_html, book_id=book["id"])

    page_id = page["id"]
    html_with_local_images, image_count = migrator._migrate_images(rendered_html, page_id)
    if image_count > 0:
        bs.update_page_html(page_id, page_name, html_with_local_images)

    read_page = bs._request("GET", f"/api/pages/{page_id}")
    page_url = read_page.get("url", "")

    print("TEST_OK")
    print(f"CONFLUENCE_PAGE_ID={conf_page_id}")
    print(f"CONFLUENCE_TITLE={conf_title}")
    print(f"BOOK_ID={book['id']}")
    print(f"BOOK_NAME={book_name}")
    print(f"BOOKSTACK_PAGE_ID={page_id}")
    print(f"BOOKSTACK_PAGE_NAME={page_name}")
    print(f"SOURCE_IMG_REFS={candidate_img_refs}")
    print(f"MIGRATED_IMAGES={image_count}")
    print(f"BOOKSTACK_PAGE_URL={page_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
