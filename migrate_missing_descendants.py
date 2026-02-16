import argparse
import os
from pathlib import Path

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, Migrator, load_config_from_env


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def conf_exact(conf: ConfluenceClient, space_key: str, title: str) -> list[dict]:
    cql = f'space="{space_key}" and type=page and title="{title}"'
    data = conf._get_json("/wiki/rest/api/content/search", {"cql": cql, "limit": 20, "expand": "body.storage,body.view"})
    return data.get("results", [])


def conf_descendants(conf: ConfluenceClient, root_id: str) -> list[dict]:
    cql = f"ancestor={root_id} and type=page"
    data = conf._get_json("/wiki/rest/api/content/search", {"cql": cql, "limit": 500, "expand": "body.storage,body.view"})
    return data.get("results", [])


def render_html(conf: ConfluenceClient, page: dict, migrator: Migrator) -> str:
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
    return html if html.strip() else "<p></p>"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-title", required=True)
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--with-images", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    migrator = Migrator(cfg, dry_run=False)

    space_name = conf.get_space_name(cfg.confluence_space_key)
    book_name = f"{cfg.book_name_prefix}{space_name}" if cfg.book_name_prefix else space_name
    book = bs.find_book_by_name(book_name) or bs.create_book(book_name, description=f"Automatisch migriert aus Confluence Space {cfg.confluence_space_key}")

    roots = conf_exact(conf, cfg.confluence_space_key, args.root_title)
    print(f"ROOT_MATCHES={len(roots)}", flush=True)

    migrated = 0
    already = 0
    existing_pages = bs._request("GET", "/api/pages?count=500").get("data", [])
    existing_names = {(p.get("name") or "") for p in existing_pages}

    for root in roots:
        root_id = str(root.get("id"))
        descendants = conf_descendants(conf, root_id)
        print(f"ROOT={args.root_title}::{root_id}::DESC={len(descendants)}", flush=True)

        for page in descendants:
            if migrated >= args.max_pages:
                break

            title = page.get("title", "Untitled")
            page_id = str(page.get("id"))
            if title in existing_names:
                already += 1
                continue

            try:
                html = render_html(conf, page, migrator)
                created = bs.create_page(title, html, book_id=book["id"])
                new_page_id = created["id"]

                image_count = 0
                if args.with_images:
                    html2, image_count = migrator._migrate_images(html, new_page_id)
                    if image_count > 0:
                        bs.update_page_html(new_page_id, title, html2)

                migrated += 1
                existing_names.add(title)
                print(f"MIGRATED={page_id}::{title}::{new_page_id}::images={image_count}", flush=True)
            except Exception as exc:
                print(f"FAILED={page_id}::{title}::{exc}", flush=True)

        if migrated >= args.max_pages:
            break

    print(f"MIGRATED_COUNT={migrated}", flush=True)
    print(f"ALREADY_PRESENT={already}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
