import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, load_config_from_env

REPORT = Path("cn_reorder_report.json")
TARGET_BOOK_NAME = "Confluence - Computer & Netzwerk"


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize(text: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " und ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_all(bs: BookStackClient, endpoint: str, count: int = 500) -> List[dict]:
    return bs._request("GET", f"{endpoint}?count={count}").get("data", [])


def page_html(detail: dict) -> str:
    html = detail.get("raw_html") or detail.get("html") or "<p></p>"
    return html if html and html.strip() else "<p></p>"


def move_and_priority(bs: BookStackClient, page_id: int, *, book_id=None, chapter_id=None, priority: int = 1) -> None:
    detail = bs._request("GET", f"/api/pages/{page_id}")
    payload = {
        "name": detail.get("name", "Untitled"),
        "html": page_html(detail),
        "priority": priority,
    }
    if chapter_id is not None:
        payload["chapter_id"] = chapter_id
    else:
        payload["book_id"] = book_id
    bs._request("PUT", f"/api/pages/{page_id}", payload)


def update_chapter_priority(bs: BookStackClient, chapter_id: int, name: str, book_id: int, priority: int) -> None:
    bs._request("PUT", f"/api/chapters/{chapter_id}", {"name": name, "book_id": book_id, "priority": priority})


def create_chapter(bs: BookStackClient, book_id: int, name: str) -> dict:
    return bs._request("POST", "/api/chapters", {"book_id": book_id, "name": name, "description": ""})


def main() -> int:
    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)

    books = get_all(bs, "/api/books")
    target = None
    for b in books:
        n = normalize(b.get("name", ""))
        slug = (b.get("slug") or "").lower()
        if n == normalize(TARGET_BOOK_NAME):
            target = b
            break
        if "confluence" in n and "computer" in n and "netzwerk" in n:
            target = b
            break
        if "confluence-computer-netzwerk" in slug:
            target = b
            break
    if not target:
        raise RuntimeError("Target CN book not found")

    target_book_id = int(target["id"])

    confluence_pages = conf.list_pages_in_space(cfg.confluence_space_key)
    page_map = {p["id"]: p for p in confluence_pages}
    child_map: Dict[str, List[str]] = {p["id"]: [] for p in confluence_pages}
    top_level: List[str] = []

    for page in confluence_pages:
        parent = None
        for anc in reversed(page.get("ancestors", []) or []):
            aid = anc.get("id")
            if aid in page_map:
                parent = aid
                break
        if parent:
            child_map[parent].append(page["id"])
        else:
            top_level.append(page["id"])

    chapters = get_all(bs, "/api/chapters")
    pages = get_all(bs, "/api/pages")
    target_chapters = [c for c in chapters if int(c.get("book_id", -1)) == target_book_id]
    target_pages = [p for p in pages if int(p.get("book_id", -1)) == target_book_id]

    ch_by_norm = {normalize(c.get("name", "")): c for c in target_chapters}
    pg_by_norm: Dict[str, List[dict]] = {}
    for p in target_pages:
        pg_by_norm.setdefault(normalize(p.get("name", "")), []).append(p)

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_book_id": target_book_id,
        "chapter_updates": [],
        "page_updates": [],
        "errors": [],
    }

    chapter_priority = 1
    page_priority = 1

    for root_id in top_level:
        root_title = page_map[root_id].get("title", "Untitled")
        has_children = len(child_map[root_id]) > 0

        if has_children:
            ch = ch_by_norm.get(normalize(root_title))
            if not ch:
                try:
                    ch = create_chapter(bs, target_book_id, root_title)
                    ch_by_norm[normalize(root_title)] = ch
                except Exception as exc:
                    report["errors"].append({"action": "create_chapter", "title": root_title, "error": str(exc)})
                    continue

            ch_id = int(ch["id"])
            try:
                update_chapter_priority(bs, ch_id, ch.get("name", root_title), target_book_id, chapter_priority)
                report["chapter_updates"].append({"chapter_id": ch_id, "priority": chapter_priority})
            except Exception as exc:
                report["errors"].append({"action": "chapter_priority", "chapter_id": ch_id, "error": str(exc)})
            chapter_priority += 1

            # root page
            root_pages = pg_by_norm.get(normalize(root_title), [])
            if root_pages:
                pid = int(root_pages[0]["id"])
                try:
                    move_and_priority(bs, pid, chapter_id=ch_id, priority=page_priority)
                    report["page_updates"].append({"page_id": pid, "priority": page_priority, "chapter_id": ch_id})
                except Exception as exc:
                    report["errors"].append({"action": "root_page_order", "page_id": pid, "error": str(exc)})
                page_priority += 1

            queue = list(child_map[root_id])
            while queue:
                nid = queue.pop(0)
                node = page_map[nid]
                anc_titles = []
                for anc in node.get("ancestors", []) or []:
                    aid = anc.get("id")
                    if aid in page_map:
                        anc_titles.append(page_map[aid].get("title", ""))
                anc_titles.append(node.get("title", "Untitled"))
                trail = " / ".join(anc_titles[1:]) if len(anc_titles) > 1 else anc_titles[0]

                candidates = pg_by_norm.get(normalize(trail), [])
                if candidates:
                    pid = int(candidates[0]["id"])
                    try:
                        move_and_priority(bs, pid, chapter_id=ch_id, priority=page_priority)
                        report["page_updates"].append({"page_id": pid, "priority": page_priority, "chapter_id": ch_id})
                    except Exception as exc:
                        report["errors"].append({"action": "child_page_order", "page_id": pid, "error": str(exc)})
                    page_priority += 1

                queue[0:0] = child_map[nid]

        else:
            candidates = pg_by_norm.get(normalize(root_title), [])
            if candidates:
                pid = int(candidates[0]["id"])
                try:
                    move_and_priority(bs, pid, book_id=target_book_id, priority=page_priority)
                    report["page_updates"].append({"page_id": pid, "priority": page_priority, "book_id": target_book_id})
                except Exception as exc:
                    report["errors"].append({"action": "top_page_order", "page_id": pid, "error": str(exc)})
                page_priority += 1

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"TARGET_BOOK_ID={target_book_id}")
    print(f"CHAPTER_UPDATES={len(report['chapter_updates'])}")
    print(f"PAGE_UPDATES={len(report['page_updates'])}")
    print(f"ERRORS={len(report['errors'])}")
    print(f"REPORT={REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
