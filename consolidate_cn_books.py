import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, Migrator, load_config_from_env

REPORT_PATH = Path("cn_books_consolidation_report.json")
TARGET_BOOK_NAME = "Confluence - Computer & Netzwerk"


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " und ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def get_all(bs: BookStackClient, endpoint: str, count: int = 500) -> List[dict]:
    data = bs._request("GET", f"{endpoint}?count={count}")
    return data.get("data", [])


def page_html(detail: dict) -> str:
    html = detail.get("raw_html") or detail.get("html") or "<p></p>"
    if not html.strip():
        return "<p></p>"
    return html


def move_page(bs: BookStackClient, page_id: int, target_book_id: Optional[int], target_chapter_id: Optional[int]) -> None:
    detail = bs._request("GET", f"/api/pages/{page_id}")
    payload = {
        "name": detail.get("name", "Untitled"),
        "html": page_html(detail),
    }
    if target_chapter_id is not None:
        payload["chapter_id"] = target_chapter_id
    elif target_book_id is not None:
        payload["book_id"] = target_book_id
    else:
        raise ValueError("Either target_book_id or target_chapter_id required")
    bs._request("PUT", f"/api/pages/{page_id}", payload)


def update_chapter(bs: BookStackClient, chapter_id: int, name: str, book_id: int, priority: Optional[int] = None) -> None:
    payload = {"name": name, "book_id": book_id}
    if priority is not None:
        payload["priority"] = priority
    bs._request("PUT", f"/api/chapters/{chapter_id}", payload)


def update_page_priority(bs: BookStackClient, page_id: int, priority: int) -> None:
    detail = bs._request("GET", f"/api/pages/{page_id}")
    payload = {
        "name": detail.get("name", "Untitled"),
        "html": page_html(detail),
        "priority": priority,
    }
    chapter_id = detail.get("chapter_id")
    if chapter_id:
        payload["chapter_id"] = chapter_id
    else:
        payload["book_id"] = detail.get("book_id")
    bs._request("PUT", f"/api/pages/{page_id}", payload)


def score_page(bs: BookStackClient, page_id: int) -> Tuple[int, int, int]:
    detail = bs._request("GET", f"/api/pages/{page_id}")
    html = page_html(detail)
    img_count = len(re.findall(r"<img\b", html, flags=re.IGNORECASE))
    return (img_count, len(html), page_id)


def build_confluence_order(conf: ConfluenceClient, space_key: str) -> Tuple[List[Tuple[str, bool]], Dict[str, str], Dict[str, List[str]]]:
    pages = conf.list_pages_in_space(space_key)
    page_map = {p["id"]: p for p in pages}
    children: Dict[str, List[str]] = {p["id"]: [] for p in pages}
    top_level: List[str] = []

    for page in pages:
        ancestors = page.get("ancestors", []) or []
        parent_id = None
        for anc in reversed(ancestors):
            anc_id = anc.get("id")
            if anc_id in page_map:
                parent_id = anc_id
                break
        if parent_id:
            children[parent_id].append(page["id"])
        else:
            top_level.append(page["id"])

    order: List[Tuple[str, bool]] = []
    trail_title_by_id: Dict[str, str] = {}

    for root_id in top_level:
        root = page_map[root_id]
        has_children = len(children[root_id]) > 0
        root_title = root.get("title", "Untitled")
        trail_title_by_id[root_id] = root_title
        order.append((root_title, has_children))

        if has_children:
            queue = list(children[root_id])
            while queue:
                node = queue.pop(0)
                chain = []
                node_page = page_map[node]
                anc = node_page.get("ancestors", []) or []
                for a in anc:
                    aid = a.get("id")
                    if aid in page_map:
                        chain.append(page_map[aid].get("title", ""))
                chain.append(node_page.get("title", "Untitled"))
                if len(chain) > 1:
                    trail = " / ".join(chain[1:])
                else:
                    trail = chain[0]
                trail_title_by_id[node] = trail
                order.append((trail, False))
                queue[0:0] = children[node]

    return order, trail_title_by_id, children


def main() -> int:
    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    migrator = Migrator(cfg, dry_run=False)

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "candidate_books": [],
        "target_book_id": None,
        "source_book_ids": [],
        "moved_chapters": [],
        "moved_pages": [],
        "deduplicated_pages": [],
        "deleted_books": [],
        "ordering_updates": [],
        "errors": [],
    }

    books = get_all(bs, "/api/books")
    chapters = get_all(bs, "/api/chapters")
    pages = get_all(bs, "/api/pages")

    target_norm = normalize(TARGET_BOOK_NAME)
    candidates = []
    for b in books:
        n = normalize(b.get("name", ""))
        slug = (b.get("slug") or "").lower()
        if n == target_norm:
            candidates.append(b)
            continue
        if "confluence" in n and "computer" in n and "netzwerk" in n:
            candidates.append(b)
            continue
        if "confluence-computer-netzwerk" in slug:
            candidates.append(b)

    # de-duplicate candidates by id (multiple match rules may hit same book)
    dedup = {}
    for b in candidates:
        dedup[int(b["id"])] = b
    candidates = list(dedup.values())

    if len(candidates) < 1:
        raise RuntimeError(f"Expected at least 1 book named like '{TARGET_BOOK_NAME}', found 0")

    chapter_count_by_book = defaultdict(int)
    page_count_by_book = defaultdict(int)
    for ch in chapters:
        bid = ch.get("book_id")
        if bid is not None:
            chapter_count_by_book[int(bid)] += 1
    for p in pages:
        bid = p.get("book_id")
        if bid is not None:
            page_count_by_book[int(bid)] += 1

    scored = []
    for b in candidates:
        bid = int(b["id"])
        score = page_count_by_book[bid] + chapter_count_by_book[bid]
        scored.append((score, -bid, b))
        report["candidate_books"].append(
            {
                "id": bid,
                "name": b.get("name"),
                "slug": b.get("slug"),
                "pages": page_count_by_book[bid],
                "chapters": chapter_count_by_book[bid],
            }
        )

    scored.sort(reverse=True)
    target_book = scored[0][2]
    target_book_id = int(target_book["id"])
    source_books = [b for _, _, b in scored[1:]]
    source_ids = [int(b["id"]) for b in source_books]

    report["target_book_id"] = target_book_id
    report["source_book_ids"] = source_ids

    # Refresh maps
    chapters = get_all(bs, "/api/chapters")
    pages = get_all(bs, "/api/pages")

    target_chapters = [c for c in chapters if int(c.get("book_id", -1)) == target_book_id]
    target_chapter_by_norm = {normalize(c.get("name", "")): c for c in target_chapters}

    for source_id in source_ids:
        source_chapters = [c for c in chapters if int(c.get("book_id", -1)) == source_id]

        # handle chapter content
        for source_ch in source_chapters:
            source_ch_id = int(source_ch["id"])
            ch_name = source_ch.get("name", "")
            norm_name = normalize(ch_name)
            match_target = target_chapter_by_norm.get(norm_name)

            if match_target:
                target_ch_id = int(match_target["id"])
                ch_pages = [p for p in pages if p.get("chapter_id") == source_ch_id]
                for p in ch_pages:
                    pid = int(p["id"])
                    try:
                        move_page(bs, pid, None, target_ch_id)
                        report["moved_pages"].append({"page_id": pid, "to_chapter_id": target_ch_id})
                    except Exception as exc:
                        report["errors"].append({"action": "move_page_to_existing_chapter", "page_id": pid, "error": str(exc)})

                try:
                    bs._request("DELETE", f"/api/chapters/{source_ch_id}")
                    report["moved_chapters"].append({"chapter_id": source_ch_id, "action": "deleted_after_merge"})
                except Exception as exc:
                    report["errors"].append({"action": "delete_source_chapter", "chapter_id": source_ch_id, "error": str(exc)})
            else:
                try:
                    update_chapter(bs, source_ch_id, ch_name, target_book_id)
                    report["moved_chapters"].append({"chapter_id": source_ch_id, "action": "reassigned_book", "to_book_id": target_book_id})
                    target_chapter_by_norm[norm_name] = {"id": source_ch_id, "name": ch_name, "book_id": target_book_id}
                except Exception as exc:
                    report["errors"].append({"action": "move_chapter", "chapter_id": source_ch_id, "error": str(exc)})

        # move loose pages from source book
        pages = get_all(bs, "/api/pages")
        loose_pages = [p for p in pages if int(p.get("book_id", -1)) == source_id and not p.get("chapter_id")]
        for p in loose_pages:
            pid = int(p["id"])
            try:
                move_page(bs, pid, target_book_id, None)
                report["moved_pages"].append({"page_id": pid, "to_book_id": target_book_id})
            except Exception as exc:
                report["errors"].append({"action": "move_loose_page", "page_id": pid, "error": str(exc)})

    # Deduplicate within target book by normalized page name
    pages = get_all(bs, "/api/pages")
    target_pages = [p for p in pages if int(p.get("book_id", -1)) == target_book_id]
    by_name: Dict[str, List[dict]] = defaultdict(list)
    for p in target_pages:
        by_name[normalize(p.get("name", ""))].append(p)

    for _, group in by_name.items():
        if len(group) <= 1:
            continue

        scored_pages = []
        for p in group:
            pid = int(p["id"])
            try:
                scored_pages.append((score_page(bs, pid), p))
            except Exception:
                scored_pages.append(((0, 0, pid), p))

        scored_pages.sort(reverse=True)
        keep = scored_pages[0][1]
        keep_id = int(keep["id"])

        for _, loser in scored_pages[1:]:
            loser_id = int(loser["id"])
            try:
                bs._request("DELETE", f"/api/pages/{loser_id}")
                report["deduplicated_pages"].append({"kept": keep_id, "deleted": loser_id, "name": loser.get("name")})
            except Exception as exc:
                report["errors"].append({"action": "delete_duplicate_page", "page_id": loser_id, "error": str(exc)})

    # Remove empty source books
    for source_id in source_ids:
        chapters = get_all(bs, "/api/chapters")
        pages = get_all(bs, "/api/pages")
        has_ch = any(int(c.get("book_id", -1)) == source_id for c in chapters)
        has_pg = any(int(p.get("book_id", -1)) == source_id for p in pages)
        if not has_ch and not has_pg:
            try:
                bs._request("DELETE", f"/api/books/{source_id}")
                report["deleted_books"].append(source_id)
            except Exception as exc:
                report["errors"].append({"action": "delete_source_book", "book_id": source_id, "error": str(exc)})

    # Apply ordering based on Confluence tree
    try:
        order, _, children = build_confluence_order(conf, cfg.confluence_space_key)
        chapters = get_all(bs, "/api/chapters")
        pages = get_all(bs, "/api/pages")
        target_chapters = [c for c in chapters if int(c.get("book_id", -1)) == target_book_id]
        target_pages = [p for p in pages if int(p.get("book_id", -1)) == target_book_id]

        ch_by_norm = {normalize(c.get("name", "")): c for c in target_chapters}
        pg_by_norm = defaultdict(list)
        for p in target_pages:
            pg_by_norm[normalize(p.get("name", ""))].append(p)

        chapter_priority = 1
        page_priority = 1
        confluence_pages = conf.list_pages_in_space(cfg.confluence_space_key)
        page_map = {p["id"]: p for p in confluence_pages}
        child_map = {p["id"]: [] for p in confluence_pages}
        top_level = []
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

        for root_id in top_level:
            root_title = page_map[root_id].get("title", "Untitled")
            has_children = len(child_map[root_id]) > 0

            if has_children:
                ch = ch_by_norm.get(normalize(root_title))
                if ch:
                    try:
                        update_chapter(bs, int(ch["id"]), ch.get("name", root_title), target_book_id, priority=chapter_priority)
                        report["ordering_updates"].append({"type": "chapter", "id": int(ch["id"]), "priority": chapter_priority})
                    except Exception as exc:
                        report["errors"].append({"action": "chapter_priority", "chapter_id": int(ch["id"]), "error": str(exc)})
                    chapter_priority += 1

                    # root page in chapter
                    root_candidates = pg_by_norm.get(normalize(root_title), [])
                    if root_candidates:
                        root_page = root_candidates[0]
                        try:
                            move_page(bs, int(root_page["id"]), None, int(ch["id"]))
                            update_page_priority(bs, int(root_page["id"]), page_priority)
                            report["ordering_updates"].append({"type": "page", "id": int(root_page["id"]), "priority": page_priority})
                            page_priority += 1
                        except Exception as exc:
                            report["errors"].append({"action": "order_root_page", "page_id": int(root_page["id"]), "error": str(exc)})

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
                            p = candidates[0]
                            pid = int(p["id"])
                            try:
                                move_page(bs, pid, None, int(ch["id"]))
                                update_page_priority(bs, pid, page_priority)
                                report["ordering_updates"].append({"type": "page", "id": pid, "priority": page_priority})
                                page_priority += 1
                            except Exception as exc:
                                report["errors"].append({"action": "order_child_page", "page_id": pid, "error": str(exc)})

                        queue[0:0] = child_map[nid]
            else:
                candidates = pg_by_norm.get(normalize(root_title), [])
                if candidates:
                    p = candidates[0]
                    pid = int(p["id"])
                    try:
                        move_page(bs, pid, target_book_id, None)
                        update_page_priority(bs, pid, page_priority)
                        report["ordering_updates"].append({"type": "page", "id": pid, "priority": page_priority})
                        page_priority += 1
                    except Exception as exc:
                        report["errors"].append({"action": "order_top_page", "page_id": pid, "error": str(exc)})

    except Exception as exc:
        report["errors"].append({"action": "ordering_pass", "error": str(exc)})

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"TARGET_BOOK_ID={target_book_id}")
    print(f"SOURCE_BOOK_IDS={','.join(str(x) for x in source_ids)}")
    print(f"MOVED_CHAPTERS={len(report['moved_chapters'])}")
    print(f"MOVED_PAGES={len(report['moved_pages'])}")
    print(f"DEDUPED_PAGES={len(report['deduplicated_pages'])}")
    print(f"DELETED_BOOKS={len(report['deleted_books'])}")
    print(f"ORDERING_UPDATES={len(report['ordering_updates'])}")
    print(f"ERRORS={len(report['errors'])}")
    print(f"REPORT={REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
