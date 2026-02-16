import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, Migrator, load_config_from_env


REPORT_FILE = Path("missing_pages_migration_report.json")


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " und ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def collect_book_tokens(page_name: str) -> List[str]:
    tokens = [normalize(page_name)]
    parts = [p.strip() for p in page_name.split("/")]
    if len(parts) > 1:
        for idx in range(len(parts)):
            suffix = " / ".join(parts[idx:]).strip()
            if suffix:
                tokens.append(normalize(suffix))
            if parts[idx]:
                tokens.append(normalize(parts[idx]))
    return [t for t in tokens if t]


def pick_rendered_html(conf: ConfluenceClient, page_data: dict) -> str:
    view_html = page_data.get("body", {}).get("view", {}).get("value", "")
    storage_html = page_data.get("body", {}).get("storage", {}).get("value", "")
    if view_html:
        return view_html
    if storage_html:
        try:
            return conf.convert_storage_to_view(storage_html)
        except Exception:
            return storage_html
    return "<p></p>"


def main() -> int:
    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    migrator = Migrator(cfg, dry_run=False)

    space_name = conf.get_space_name(cfg.confluence_space_key)
    book_name = f"{cfg.book_name_prefix}{space_name}" if cfg.book_name_prefix else space_name
    book = bs.find_book_by_name(book_name)
    if not book:
        book = bs.create_book(book_name, description=f"Automatisch migriert aus Confluence Space {cfg.confluence_space_key}")

    conf_pages = conf.list_pages_in_space(cfg.confluence_space_key)
    bs_pages = bs._request("GET", "/api/pages?count=500").get("data", [])
    existing_exact_titles = {(item.get("name") or "") for item in bs_pages}

    book_tokens = set()
    for item in bs_pages:
        for token in collect_book_tokens(item.get("name", "")):
            book_tokens.add(token)

    missing_pages = []
    for page in conf_pages:
        title = page.get("title", "")
        title_norm = normalize(title)
        if title_norm and title_norm not in book_tokens:
            missing_pages.append(page)

    created = []
    skipped = []
    errors = []

    for idx, page in enumerate(missing_pages, start=1):
        conf_page_id = page.get("id")
        title = page.get("title", "Untitled")
        try:
            rendered_html = pick_rendered_html(conf, page)
            rendered_html = migrator._normalize_html_links(rendered_html)
            if not rendered_html.strip():
                rendered_html = "<p></p>"

            if title in existing_exact_titles:
                skipped.append({"id": conf_page_id, "title": title, "reason": "already exists by exact title"})
                continue

            new_page = bs.create_page(title, rendered_html, book_id=book["id"])
            new_page_id = new_page["id"]

            html_with_images, image_count = migrator._migrate_images(rendered_html, new_page_id)
            if image_count > 0 and html_with_images.strip():
                bs.update_page_html(new_page_id, title, html_with_images)

            created.append(
                {
                    "confluence_page_id": conf_page_id,
                    "confluence_title": title,
                    "bookstack_page_id": new_page_id,
                    "migrated_images": image_count,
                    "index": idx,
                }
            )
            existing_exact_titles.add(title)
        except Exception as exc:
            errors.append({"confluence_page_id": conf_page_id, "title": title, "error": str(exc)})

    report: Dict[str, object] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "space_key": cfg.confluence_space_key,
        "book_id": book.get("id"),
        "book_name": book.get("name"),
        "confluence_total": len(conf_pages),
        "bookstack_total_before": len(bs_pages),
        "missing_detected": len(missing_pages),
        "created_count": len(created),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }

    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"MISSING_DETECTED={len(missing_pages)}")
    print(f"CREATED={len(created)}")
    print(f"SKIPPED={len(skipped)}")
    print(f"ERRORS={len(errors)}")
    print(f"REPORT={REPORT_FILE}")

    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
