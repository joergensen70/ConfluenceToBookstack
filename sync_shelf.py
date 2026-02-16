from pathlib import Path
import traceback

import requests


def load_env(path: str) -> dict:
    env = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#') or '=' not in s:
            continue
        key, value = s.split('=', 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


result_lines = []

try:
    env = load_env('.env')
    base = env['BOOKSTACK_BASE_URL'].rstrip('/')
    auth = f"Token {env['BOOKSTACK_TOKEN_ID']}:{env['BOOKSTACK_TOKEN_SECRET']}"
    headers = {'Authorization': auth, 'Accept': 'application/json'}
    json_headers = {'Authorization': auth, 'Accept': 'application/json', 'Content-Type': 'application/json'}

    books_resp = requests.get(f"{base}/api/books?count=500", headers=headers, timeout=60)
    books_resp.raise_for_status()
    books = books_resp.json().get('data', [])

    migration_books = [b for b in books if (b.get('name') or '').startswith('Confluence -')]
    book_ids = [int(b['id']) for b in migration_books]

    shelves_resp = requests.get(f"{base}/api/shelves?count=500", headers=headers, timeout=60)
    shelves_resp.raise_for_status()
    shelves = shelves_resp.json().get('data', [])
    shelf = next((s for s in shelves if s.get('name') == 'Confluence Migration'), None)

    if shelf is None:
        create_payload = {
            'name': 'Confluence Migration',
            'description': 'Automatisch zugewiesene Confluence-Migrationsbücher',
            'books': book_ids,
        }
        create_resp = requests.post(f"{base}/api/shelves", headers=json_headers, json=create_payload, timeout=60)
        create_resp.raise_for_status()
        shelf = create_resp.json()

    shelf_id = int(shelf['id'])
    update_payload = {'name': 'Confluence Migration', 'books': book_ids}
    update_resp = requests.put(f"{base}/api/shelves/{shelf_id}", headers=json_headers, json=update_payload, timeout=60)
    if update_resp.status_code >= 400:
        form_resp = requests.put(
            f"{base}/api/shelves/{shelf_id}",
            headers=headers,
            data=[('name', 'Confluence Migration')] + [('books[]', str(bid)) for bid in book_ids],
            timeout=60,
        )
        form_resp.raise_for_status()
    else:
        update_resp.raise_for_status()

    detail_resp = requests.get(f"{base}/api/shelves/{shelf_id}", headers=headers, timeout=60)
    detail_resp.raise_for_status()
    detail = detail_resp.json()

    result_lines.append("STATUS=OK")
    result_lines.append(f"SHELF_ID={shelf_id}")
    result_lines.append(f"MIGRATION_BOOKS_FOUND={len(migration_books)}")
    for b in sorted(migration_books, key=lambda x: x.get('id', 0)):
        result_lines.append(f"BOOK={b['id']}:{b['name']}")
    result_lines.append(f"SHELF_BOOKS_TOTAL={len(detail.get('books', []))}")
    for b in sorted(detail.get('books', []), key=lambda x: x.get('id', 0)):
        result_lines.append(f"SHELF_BOOK={b['id']}:{b['name']}")
except Exception as exc:
    result_lines.append("STATUS=ERROR")
    result_lines.append(f"ERROR={exc}")
    result_lines.extend(traceback.format_exc().splitlines())

Path('shelf_sync_result.txt').write_text("\n".join(result_lines), encoding='utf-8')
for line in result_lines:
    print(line)
