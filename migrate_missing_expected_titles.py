import json
import os
from pathlib import Path

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, Migrator, load_config_from_env

REPORT = Path("cn_content_diff_cleanup_report.json")


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def esc_cql(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    migrator = Migrator(cfg, dry_run=False)

    data = json.loads(REPORT.read_text(encoding='utf-8'))
    missing = data.get('missing_expected', [])

    books = bs._request('GET', '/api/books?count=500').get('data', [])
    target = None
    for b in books:
        name = (b.get('name') or '').lower()
        slug = (b.get('slug') or '').lower()
        if ('confluence' in name and 'computer' in name and 'netzwerk' in name) or ('confluence-computer-netzwerk' in slug):
            target = b
            break
    if not target:
        raise RuntimeError('CN target book not found')

    target_id = int(target['id'])

    migrated = 0
    for title in missing:
        # check exists already
        existing = bs._request('GET', '/api/pages?count=500').get('data', [])
        if any((p.get('name') or '') == title and int(p.get('book_id', -1)) == target_id for p in existing):
            print(f'SKIP_EXISTS={title}')
            continue

        cql = f'space="{cfg.confluence_space_key}" and type=page and title="{esc_cql(title)}"'
        hits = conf._get_json('/wiki/rest/api/content/search', {'cql': cql, 'limit': 10, 'expand': 'body.storage,body.view'}).get('results', [])
        if not hits:
            print(f'NOT_FOUND_IN_CONF={title}')
            continue

        page = hits[0]
        view_html = page.get('body', {}).get('view', {}).get('value', '')
        storage_html = page.get('body', {}).get('storage', {}).get('value', '')
        if view_html:
            html = view_html
        else:
            try:
                html = conf.convert_storage_to_view(storage_html)
            except Exception:
                html = storage_html

        html = migrator._normalize_html_links(html or '<p></p>')
        if not html.strip():
            html = '<p></p>'

        created = bs.create_page(title, html, book_id=target_id)
        pid = int(created['id'])

        html2, image_count = migrator._migrate_images(html, pid)
        if image_count > 0:
            bs.update_page_html(pid, title, html2)

        migrated += 1
        print(f'MIGRATED={title}::{pid}::images={image_count}')

    print(f'MIGRATED_COUNT={migrated}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
