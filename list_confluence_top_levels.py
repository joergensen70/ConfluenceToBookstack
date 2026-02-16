import os
from pathlib import Path

from confluence_to_bookstack_migration import ConfluenceClient, load_config_from_env


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
    conf=ConfluenceClient(cfg.confluence_base_url,cfg.confluence_email,cfg.confluence_api_token)
    pages=conf.list_pages_in_space(cfg.confluence_space_key)
    page_map={p['id']:p for p in pages}

    top=[]
    for p in pages:
        parent=None
        for anc in reversed(p.get('ancestors',[]) or []):
            aid=anc.get('id')
            if aid in page_map:
                parent=aid
                break
        if parent is None:
            top.append(p)

    print('TOP_LEVEL_COUNT='+str(len(top)))
    for p in top:
        print('TOP='+str(p.get('id'))+'::'+str(p.get('title','')))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
