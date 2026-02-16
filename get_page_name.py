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


def main() -> int:
    load_dotenv(Path('.env'))
    cfg=load_config_from_env()
    bs=BookStackClient(cfg.bookstack_base_url,cfg.bookstack_token_id,cfg.bookstack_token_secret)
    p=bs._request('GET','/api/pages/221')
    print('PAGE_ID='+str(p.get('id')))
    print('NAME='+str(p.get('name','')))
    print('BOOK_ID='+str(p.get('book_id')))
    print('CHAPTER_ID='+str(p.get('chapter_id')))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
