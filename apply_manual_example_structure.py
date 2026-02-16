import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

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


def get_all(bs: BookStackClient, endpoint: str):
    return bs._request('GET', f'{endpoint}?count=500').get('data',[])


def ensure_book(bs: BookStackClient, name: str) -> dict:
    books = get_all(bs,'/api/books')
    n = norm(name)
    for b in books:
        if norm(b.get('name','')) == n:
            return b
    return bs.create_book(name, description='Manuell nach Confluence-Struktur angelegt')


def ensure_chapter(bs: BookStackClient, book_id: int, name: str) -> dict:
    chapters = get_all(bs,'/api/chapters')
    n = norm(name)
    for c in chapters:
        if int(c.get('book_id',-1))==int(book_id) and norm(c.get('name',''))==n:
            return c
    return bs.create_chapter(book_id, name)


def find_page(bs: BookStackClient, needle: str) -> Optional[dict]:
    pages = get_all(bs,'/api/pages')
    n = norm(needle)

    # exact normalized
    for p in pages:
        if norm(p.get('name','')) == n:
            return p

    # contains normalized token
    for p in pages:
        if n in norm(p.get('name','')):
            return p

    return None


def move_page_to_chapter(bs: BookStackClient, page_id: int, chapter_id: int, new_name: Optional[str]=None) -> None:
    detail = bs._request('GET', f'/api/pages/{page_id}')
    payload = {
        'name': new_name or detail.get('name','Untitled'),
        'html': detail.get('raw_html') or detail.get('html') or '<p></p>',
        'chapter_id': int(chapter_id),
    }
    bs._request('PUT', f'/api/pages/{page_id}', payload)


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    # Books as requested
    book_volk = ensure_book(bs, 'Volkszähler')
    book_anl = ensure_book(bs, 'Anleitungsartikel')
    book_moved = ensure_book(bs, 'Moved to bookstack')
    book_putty = ensure_book(bs, 'Putty')

    # Chapters as requested
    ch_img = ensure_chapter(bs, int(book_volk['id']), '1 Volkzaehler Image aufspielen')
    ch_rs = ensure_chapter(bs, int(book_anl['id']), 'RS485/MQTT Adapter')
    ch_joomla = ensure_chapter(bs, int(book_moved['id']), 'Joomla Update')
    ch_linux = ensure_chapter(bs, int(book_moved['id']), 'Linux Befehle')

    # Pages as requested
    sd = find_page(bs, 'SD Karte mit SD Formater')
    if sd:
        move_page_to_chapter(bs, int(sd['id']), int(ch_img['id']), new_name=sd.get('name'))
        print(f"MOVED_SD_PAGE={sd.get('id')}")
    else:
        print("MISSING_SD_PAGE")

    find_page_item = find_page(bs, 'find')
    if find_page_item:
        move_page_to_chapter(bs, int(find_page_item['id']), int(ch_linux['id']), new_name=find_page_item.get('name'))
        print(f"MOVED_FIND_PAGE={find_page_item.get('id')}")
    else:
        print("MISSING_FIND_PAGE")

    print(f"BOOK_VOLKS={book_volk.get('id')}")
    print(f"BOOK_ANLEITUNGSARTIKEL={book_anl.get('id')}")
    print(f"BOOK_MOVED={book_moved.get('id')}")
    print(f"BOOK_PUTTY={book_putty.get('id')}")
    print(f"CHAPTER_IMG={ch_img.get('id')}")
    print(f"CHAPTER_RS485={ch_rs.get('id')}")
    print(f"CHAPTER_JOOMLA={ch_joomla.get('id')}")
    print(f"CHAPTER_LINUX={ch_linux.get('id')}")

    return 0


if __name__=='__main__':
    raise SystemExit(main())
