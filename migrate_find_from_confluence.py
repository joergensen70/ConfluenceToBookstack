import os
from pathlib import Path

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, Migrator, load_config_from_env


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k,v=line.split('=',1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def norm(s: str) -> str:
    import re, unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    migrator = Migrator(cfg, dry_run=False)

    books = bs._request('GET','/api/books?count=500').get('data',[])
    chapters = bs._request('GET','/api/chapters?count=500').get('data',[])
    pages = bs._request('GET','/api/pages?count=500').get('data',[])

    moved_book = next((b for b in books if norm(b.get('name','')) == norm('Moved to bookstack')), None)
    if not moved_book:
        print('MISSING_BOOK')
        return 2

    linux_ch = next((c for c in chapters if int(c.get('book_id',-1))==int(moved_book['id']) and norm(c.get('name',''))==norm('Linux Befehle')), None)
    if not linux_ch:
        print('MISSING_LINUX_CHAPTER')
        return 2

    # already exists?
    for p in pages:
        if int(p.get('chapter_id') or -1)==int(linux_ch['id']) and norm(p.get('name','')) == norm('Find'):
            print(f'ALREADY_EXISTS={p.get("id")}')
            return 0

    cql = f'space="{cfg.confluence_space_key}" and type=page and title~"Find"'
    hits = conf._get_json('/wiki/rest/api/content/search', {'cql': cql, 'limit': 50, 'expand': 'body.storage,body.view'}).get('results', [])

    best = None
    for h in hits:
        t = h.get('title','')
        if norm(t) == norm('Find'):
            best = h
            break
    if best is None and hits:
        best = hits[0]

    if best is None:
        print('NO_CONF_FIND_PAGE')
        return 0

    title = best.get('title','Find')
    view_html = best.get('body',{}).get('view',{}).get('value','')
    storage_html = best.get('body',{}).get('storage',{}).get('value','')
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

    created = bs.create_page(title, html, chapter_id=int(linux_ch['id']))
    pid = int(created['id'])

    html2, image_count = migrator._migrate_images(html, pid)
    if image_count > 0:
        bs.update_page_html(pid, title, html2)

    print(f'CREATED_FIND_PAGE={pid}::{title}::chapter={linux_ch.get("id")}::images={image_count}')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
