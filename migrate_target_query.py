import argparse
import os
from pathlib import Path

import requests

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, Migrator, load_config_from_env


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    args = parser.parse_args()

    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    migrator = Migrator(cfg, dry_run=False)

    space_name = conf.get_space_name(cfg.confluence_space_key)
    book_name = f"{cfg.book_name_prefix}{space_name}" if cfg.book_name_prefix else space_name
    book = bs.find_book_by_name(book_name) or bs.create_book(book_name, description=f"Automatisch migriert aus Confluence Space {cfg.confluence_space_key}")

    cql = f'space="{cfg.confluence_space_key}" and type=page and title~"{args.query}"'
    conf_hits = conf._get_json("/wiki/rest/api/content/search", {"cql": cql, "limit": 100, "expand": "body.storage,body.view"}).get("results", [])

    print(f"CONF_HITS={len(conf_hits)}", flush=True)

    migrated = 0
    for page in conf_hits:
        title = page.get("title", "Untitled")
        page_id = page.get("id")

        book_hits = requests.get(
            f"{cfg.bookstack_base_url.rstrip('/')}/api/pages",
            params={"count": 100, "filter[name:like]": title},
            headers={"Authorization": f"Token {cfg.bookstack_token_id}:{cfg.bookstack_token_secret}", "Accept": "application/json"},
            timeout=60,
        )
        book_hits.raise_for_status()
        if len(book_hits.json().get("data", [])) > 0:
            print(f"SKIP_EXISTS={title}", flush=True)
            continue

        view_html = page.get("body", {}).get("view", {}).get("value", "")
        storage_html = page.get("body", {}).get("storage", {}).get("value", "")
        if view_html:
            html = view_html
        else:
            try:
                html = conf.convert_storage_to_view(storage_html)
            except Exception:
                html = storage_html

        html = migrator._normalize_html_links(html or "<p></p>")
        if not html.strip():
            html = "<p></p>"

        new_page = bs.create_page(title, html, book_id=book["id"])
        new_page_id = new_page["id"]

        html2, image_count = migrator._migrate_images(html, new_page_id)
        if image_count > 0:
            bs.update_page_html(new_page_id, title, html2)

        migrated += 1
        print(f"MIGRATED={page_id}::{title}::{new_page_id}::images={image_count}", flush=True)

    print(f"MIGRATED_COUNT={migrated}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
