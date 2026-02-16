import os
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
    return (s or '').lower().strip()


def main() -> int:
    load_dotenv(Path('.env'))
    cfg=load_config_from_env()
    bs=BookStackClient(cfg.bookstack_base_url,cfg.bookstack_token_id,cfg.bookstack_token_secret)

    books=bs._request('GET','/api/books?count=500').get('data',[])
    chapters=bs._request('GET','/api/chapters?count=500').get('data',[])
    pages=bs._request('GET','/api/pages?count=500').get('data',[])

    def find_book(name):
        for b in books:
            if norm(b.get('name'))==norm(name):
                return b
        return None

    def find_chapter(book_id, name):
        for c in chapters:
            if int(c.get('book_id',-1))==int(book_id) and norm(c.get('name'))==norm(name):
                return c
        return None

    def find_page_in_chapter(chapter_id, name_part):
        for p in pages:
            if int(p.get('chapter_id') or -1)==int(chapter_id) and name_part.lower() in (p.get('name') or '').lower():
                return p
        return None

    checks = [
        ('Volkszähler','1 Volkzaehler Image aufspielen','SD Karte mit SD Formater'),
        ('Anleitungsartikel','RS485/MQTT Adapter',None),
        ('Moved to bookstack','Joomla Update',None),
        ('Moved to bookstack','Linux Befehle','find'),
        ('Putty',None,None),
    ]

    for book_name, chapter_name, page_part in checks:
        b=find_book(book_name)
        print(f'BOOK[{book_name}]=' + ('OK:'+str(b.get('id')) if b else 'MISSING'))
        if not b or not chapter_name:
            continue
        ch=find_chapter(b['id'],chapter_name)
        print(f'  CHAPTER[{chapter_name}]=' + ('OK:'+str(ch.get('id')) if ch else 'MISSING'))
        if not ch or not page_part:
            continue
        p=find_page_in_chapter(ch['id'],page_part)
        print(f'    PAGE_CONTAINS[{page_part}]=' + ('OK:'+str(p.get('id'))+':'+str(p.get('name')) if p else 'MISSING'))

    return 0


if __name__=='__main__':
    raise SystemExit(main())
