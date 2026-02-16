import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, load_config_from_env

REPORT = Path("cn_structure_rebuild_report.json")


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " und ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_all(bs: BookStackClient, endpoint: str, count: int = 500) -> List[dict]:
    return bs._request("GET", f"{endpoint}?count={count}").get("data", [])


def page_html(detail: dict) -> str:
    html = detail.get("raw_html") or detail.get("html") or "<p></p>"
    return html if html.strip() else "<p></p>"


def move_page(bs: BookStackClient, page_id: int, *, book_id: Optional[int], chapter_id: Optional[int], priority: Optional[int]) -> None:
    detail = bs._request("GET", f"/api/pages/{page_id}")
    payload = {
        "name": detail.get("name", "Untitled"),
        "html": page_html(detail),
    }
    if priority is not None:
        payload["priority"] = priority
    if chapter_id is not None:
        payload["chapter_id"] = chapter_id
    elif book_id is not None:
        payload["book_id"] = book_id
    bs._request("PUT", f"/api/pages/{page_id}", payload)


def ensure_chapter(bs: BookStackClient, existing_by_norm: Dict[str, dict], book_id: int, title: str) -> dict:
    key = norm(title)
    if key in existing_by_norm:
        return existing_by_norm[key]
    ch = bs._request("POST", "/api/chapters", {"book_id": book_id, "name": title, "description": ""})
    existing_by_norm[key] = ch
    return ch


def set_chapter_priority(bs: BookStackClient, chapter: dict, book_id: int, priority: int) -> None:
    bs._request(
        "PUT",
        f"/api/chapters/{chapter['id']}",
        {"name": chapter.get("name", "Untitled"), "book_id": book_id, "priority": priority},
    )


def pick_candidate(pg_by_norm: Dict[str, List[dict]], used_ids: set[int], names: List[str]) -> Optional[dict]:
    for name in names:
        key = norm(name)
        for item in pg_by_norm.get(key, []):
            pid = int(item.get("id", -1))
            if pid not in used_ids:
                return item
    return None


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()

    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)

    books = get_all(bs, "/api/books")
    target = None
    for b in books:
        n = norm(b.get("name", ""))
        slug = (b.get("slug") or "").lower()
        if ("confluence" in n and "computer" in n and "netzwerk" in n) or ("confluence-computer-netzwerk" in slug):
            target = b
            break
    if not target:
        raise RuntimeError("CN target book not found")

    target_book_id = int(target["id"])

    pages = get_all(bs, "/api/pages")
    chapters = get_all(bs, "/api/chapters")
    target_pages = [p for p in pages if int(p.get("book_id", -1)) == target_book_id]
    target_chapters = [c for c in chapters if int(c.get("book_id", -1)) == target_book_id]

    pg_by_norm: Dict[str, List[dict]] = {}
    for p in target_pages:
        pg_by_norm.setdefault(norm(p.get("name", "")), []).append(p)

    ch_by_norm = {norm(c.get("name", "")): c for c in target_chapters}

    conf_pages = conf.list_pages_in_space(cfg.confluence_space_key)
    page_map = {p["id"]: p for p in conf_pages}
    child_map: Dict[str, List[str]] = {p["id"]: [] for p in conf_pages}
    top_level: List[str] = []

    for p in conf_pages:
        parent = None
        for anc in reversed(p.get("ancestors", []) or []):
            aid = anc.get("id")
            if aid in page_map:
                parent = aid
                break
        if parent:
            child_map[parent].append(p["id"])
        else:
            top_level.append(p["id"])

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_book_id": target_book_id,
        "chapter_updates": [],
        "page_moves": [],
        "errors": [],
    }

    used_ids: set[int] = set()
    chapter_priority = 1
    page_priority = 1

    for root_id in top_level:
        root = page_map[root_id]
        root_title = root.get("title", "Untitled")
        has_children = len(child_map[root_id]) > 0

        if has_children:
            try:
                chapter = ensure_chapter(bs, ch_by_norm, target_book_id, root_title)
                set_chapter_priority(bs, chapter, target_book_id, chapter_priority)
                report["chapter_updates"].append({"chapter_id": int(chapter["id"]), "name": chapter.get("name"), "priority": chapter_priority})
            except Exception as exc:
                report["errors"].append({"action": "ensure_or_order_chapter", "title": root_title, "error": str(exc)})
                continue
            chapter_priority += 1

            root_candidate = pick_candidate(pg_by_norm, used_ids, [root_title])
            if root_candidate:
                pid = int(root_candidate["id"])
                try:
                    move_page(bs, pid, book_id=None, chapter_id=int(chapter["id"]), priority=page_priority)
                    report["page_moves"].append({"page_id": pid, "title": root_candidate.get("name"), "chapter_id": int(chapter["id"]), "priority": page_priority})
                    used_ids.add(pid)
                except Exception as exc:
                    report["errors"].append({"action": "move_root_page", "page_id": pid, "error": str(exc)})
                page_priority += 1

            queue = list(child_map[root_id])
            while queue:
                node_id = queue.pop(0)
                node = page_map[node_id]
                node_title = node.get("title", "Untitled")

                anc_titles = []
                for anc in node.get("ancestors", []) or []:
                    aid = anc.get("id")
                    if aid in page_map:
                        anc_titles.append(page_map[aid].get("title", ""))
                anc_titles.append(node_title)
                trail = " / ".join(anc_titles[1:]) if len(anc_titles) > 1 else node_title

                candidate = pick_candidate(pg_by_norm, used_ids, [trail, node_title])
                if candidate:
                    pid = int(candidate["id"])
                    try:
                        move_page(bs, pid, book_id=None, chapter_id=int(chapter["id"]), priority=page_priority)
                        report["page_moves"].append({"page_id": pid, "title": candidate.get("name"), "chapter_id": int(chapter["id"]), "priority": page_priority})
                        used_ids.add(pid)
                    except Exception as exc:
                        report["errors"].append({"action": "move_child_page", "page_id": pid, "error": str(exc)})
                    page_priority += 1

                queue[0:0] = child_map[node_id]

        else:
            candidate = pick_candidate(pg_by_norm, used_ids, [root_title])
            if candidate:
                pid = int(candidate["id"])
                try:
                    move_page(bs, pid, book_id=target_book_id, chapter_id=None, priority=page_priority)
                    report["page_moves"].append({"page_id": pid, "title": candidate.get("name"), "book_id": target_book_id, "priority": page_priority})
                    used_ids.add(pid)
                except Exception as exc:
                    report["errors"].append({"action": "move_top_page", "page_id": pid, "error": str(exc)})
                page_priority += 1

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"TARGET_BOOK_ID={target_book_id}")
    print(f"CHAPTER_UPDATES={len(report['chapter_updates'])}")
    print(f"PAGE_MOVES={len(report['page_moves'])}")
    print(f"ERRORS={len(report['errors'])}")
    print(f"REPORT={REPORT}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
