import os
import re
import unicodedata
from pathlib import Path

from confluence_to_bookstack_migration import BookStackClient, load_config_from_env


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k,v=line.split('=',1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

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

    candidates=[]
    for p in pages:
        n = norm(p.get('name',''))
        if n == 'find':
            candidates.append((3,p))
        elif n.startswith('find '):
            candidates.append((2,p))
        elif ' find ' in f' {n} ':
            candidates.append((1,p))

    if not candidates:
        # debug sample
        print('NO_FIND_PAGE')
        for p in pages[:30]:
            if 'linux' in norm(p.get('name','')) or 'befehle' in norm(p.get('name','')):
                print('HINT='+str(p.get('id'))+'::'+str(p.get('name')))
        return 0

    candidates.sort(key=lambda x:(-x[0], int(x[1].get('id',0))))
    page = candidates[0][1]
    pid = int(page['id'])

    detail = bs._request('GET',f'/api/pages/{pid}')
    payload = {
        'name': detail.get('name','Untitled'),
        'html': detail.get('raw_html') or detail.get('html') or '<p></p>',
        'chapter_id': int(linux_ch['id']),
    }
    bs._request('PUT',f'/api/pages/{pid}',payload)

    print(f'MOVED_FIND_PAGE={pid}::{detail.get("name","")}::chapter={linux_ch.get("id")}')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
