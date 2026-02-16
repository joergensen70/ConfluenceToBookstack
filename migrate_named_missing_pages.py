import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, Migrator, load_config_from_env

TARGETS = [
    "Web Cam",
    "Anleitungsartikel",
    "RS485/Modbus Stromzähler",
    "Outlook 365 winmail.dat",
    "Moved to bookstack",
    "Optional Hostname",
]
ROOTS_WITH_DESCENDANTS = {"Anleitungsartikel", "Moved to bookstack"}
REPORT = Path("named_missing_migration_report.json")


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def conf_search(conf: ConfluenceClient, space_key: str, query: str) -> List[dict]:
    cql = f'space="{space_key}" and type=page and title~"{query}"'
    data = conf._get_json("/wiki/rest/api/content/search", {"cql": cql, "limit": 100, "expand": "body.storage,body.view"})
    return data.get("results", [])


def conf_exact(conf: ConfluenceClient, space_key: str, title: str) -> List[dict]:
    cql = f'space="{space_key}" and type=page and title="{title}"'
    data = conf._get_json("/wiki/rest/api/content/search", {"cql": cql, "limit": 20, "expand": "body.storage,body.view"})
    return data.get("results", [])


def conf_descendants(conf: ConfluenceClient, root_id: str) -> List[dict]:
    cql = f"ancestor={root_id} and type=page"
    data = conf._get_json("/wiki/rest/api/content/search", {"cql": cql, "limit": 500, "expand": "body.storage,body.view"})
    return data.get("results", [])


def book_title_hits(base_url: str, token_id: str, token_secret: str, title: str) -> List[dict]:
    response = requests.get(
        f"{base_url.rstrip('/')}/api/pages",
        params={"count": 500, "filter[name:like]": title},
        headers={"Authorization": f"Token {token_id}:{token_secret}", "Accept": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def get_page_html(conf: ConfluenceClient, page: dict, migrator: Migrator) -> str:
    view_html = page.get("body", {}).get("view", {}).get("value", "")
    storage_html = page.get("body", {}).get("storage", {}).get("value", "")
    if view_html:
        html = view_html
    elif storage_html:
        try:
            html = conf.convert_storage_to_view(storage_html)
        except Exception:
            html = storage_html
    else:
        html = "<p></p>"
    html = migrator._normalize_html_links(html)
    return html if html.strip() else "<p></p>"


def main() -> int:
    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    migrator = Migrator(cfg, dry_run=False)

    space_name = conf.get_space_name(cfg.confluence_space_key)
    book_name = f"{cfg.book_name_prefix}{space_name}" if cfg.book_name_prefix else space_name
    book = bs.find_book_by_name(book_name) or bs.create_book(book_name, description=f"Automatisch migriert aus Confluence Space {cfg.confluence_space_key}")

    to_migrate: Dict[str, dict] = {}
    target_status = []

    for target in TARGETS:
        conf_hits = conf_search(conf, cfg.confluence_space_key, target)
        book_hits = book_title_hits(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret, target)

        target_status.append(
            {
                "target": target,
                "confluence_matches": [p.get("title", "") for p in conf_hits],
                "bookstack_matches_before": [p.get("name", "") for p in book_hits],
            }
        )

        if len(book_hits) == 0:
            for page in conf_hits:
                to_migrate[str(page.get("id"))] = page

        if target in ROOTS_WITH_DESCENDANTS:
            roots = conf_exact(conf, cfg.confluence_space_key, target)
            for root in roots:
                root_id = str(root.get("id"))
                descendants = conf_descendants(conf, root_id)
                for child in descendants:
                    child_title = child.get("title", "")
                    child_book_hits = book_title_hits(
                        cfg.bookstack_base_url,
                        cfg.bookstack_token_id,
                        cfg.bookstack_token_secret,
                        child_title,
                    )
                    if len(child_book_hits) == 0:
                        to_migrate[str(child.get("id"))] = child

    created = []
    errors = []

    existing_pages = bs._request("GET", "/api/pages?count=500").get("data", [])
    existing_names = {(p.get("name") or "") for p in existing_pages}

    for page_id, page in to_migrate.items():
        title = page.get("title", "Untitled")
        if title in existing_names:
            continue
        try:
            html = get_page_html(conf, page, migrator)
            new_page = bs.create_page(title, html, book_id=book["id"])
            new_page_id = new_page["id"]

            html2, image_count = migrator._migrate_images(html, new_page_id)
            if image_count > 0:
                bs.update_page_html(new_page_id, title, html2)

            created.append(
                {
                    "confluence_page_id": page_id,
                    "title": title,
                    "bookstack_page_id": new_page_id,
                    "migrated_images": image_count,
                }
            )
            existing_names.add(title)
        except Exception as exc:
            errors.append({"confluence_page_id": page_id, "title": title, "error": str(exc)})

    target_status_after = []
    for target in TARGETS:
        post_hits = book_title_hits(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret, target)
        target_status_after.append(
            {
                "target": target,
                "bookstack_matches_after": [p.get("name", "") for p in post_hits],
            }
        )

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "book": {"id": book.get("id"), "name": book.get("name")},
        "targets_before": target_status,
        "migrated_count": len(created),
        "migrated": created,
        "errors_count": len(errors),
        "errors": errors,
        "targets_after": target_status_after,
    }

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"TO_MIGRATE={len(to_migrate)}")
    print(f"MIGRATED={len(created)}")
    print(f"ERRORS={len(errors)}")
    print(f"REPORT={REPORT}")

    return 0 if len(errors) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
