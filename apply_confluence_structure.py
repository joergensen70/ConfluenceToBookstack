import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, load_config_from_env

REPORT = Path("apply_confluence_structure_report.json")


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


def text_excerpt_from_html(html: str, limit: int = 900) -> str:
    html = html or ""
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = re.sub(r"\s+", " ", html).strip()
    if len(html) > limit:
        return html[:limit] + "..."
    return html


def get_all(bs: BookStackClient, endpoint: str, count: int = 500) -> List[dict]:
    return bs._request("GET", f"{endpoint}?count={count}").get("data", [])


def build_tree(conf_pages: List[dict]) -> Tuple[Dict[str, dict], Dict[str, List[str]], List[str], Dict[str, Optional[str]], Dict[str, int]]:
    page_map = {p["id"]: p for p in conf_pages}
    children: Dict[str, List[str]] = {p["id"]: [] for p in conf_pages}
    parent: Dict[str, Optional[str]] = {p["id"]: None for p in conf_pages}
    top_level: List[str] = []

    for page in conf_pages:
        pid = page["id"]
        parent_id = None
        for anc in reversed(page.get("ancestors", []) or []):
            aid = anc.get("id")
            if aid in page_map:
                parent_id = aid
                break
        parent[pid] = parent_id
        if parent_id:
            children[parent_id].append(pid)
        else:
            top_level.append(pid)

    depth: Dict[str, int] = {}

    def compute_depth(pid: str) -> int:
        if pid in depth:
            return depth[pid]
        pp = parent.get(pid)
        if pp is None:
            depth[pid] = 0
        else:
            depth[pid] = compute_depth(pp) + 1
        return depth[pid]

    for pid in page_map:
        compute_depth(pid)

    return page_map, children, top_level, parent, depth


def find_root_ancestor(pid: str, parent: Dict[str, Optional[str]], depth: Dict[str, int]) -> str:
    cur = pid
    while parent.get(cur) is not None:
        cur = parent[cur]  # type: ignore[index]
    return cur


def find_first_level_ancestor(pid: str, parent: Dict[str, Optional[str]], depth: Dict[str, int]) -> Optional[str]:
    cur = pid
    while True:
        pp = parent.get(cur)
        if pp is None:
            return None
        if depth.get(pp, 0) == 1:
            return pp
        cur = pp


def desired_page_name(pid: str, page_map: Dict[str, dict], parent: Dict[str, Optional[str]], depth: Dict[str, int]) -> str:
    d = depth[pid]
    title = page_map[pid].get("title", "Untitled")
    if d <= 2:
        return title

    # depth > 2: collapse deeper hierarchy into title trail under chapter
    chain = []
    cur: Optional[str] = pid
    while cur is not None:
        chain.append(cur)
        cur = parent.get(cur)
    chain.reverse()  # root ... pid

    # keep from depth 2 onward as page title path
    titles = [page_map[x].get("title", "") for x in chain[2:]]
    return " / ".join(titles) if titles else title


def choose_page_candidate(
    aliases: List[str],
    index_by_norm: Dict[str, List[dict]],
    used_ids: set[int],
) -> Optional[dict]:
    for alias in aliases:
        key = norm(alias)
        for item in index_by_norm.get(key, []):
            pid = int(item.get("id", -1))
            if pid not in used_ids:
                return item
    return None


def main() -> int:
    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    conf_pages = conf.list_pages_in_space(cfg.confluence_space_key)
    page_map, children, top_level, parent, depth = build_tree(conf_pages)

    books = get_all(bs, "/api/books")
    chapters = get_all(bs, "/api/chapters")
    pages = get_all(bs, "/api/pages")

    # index existing entities
    books_by_norm = defaultdict(list)
    for b in books:
        books_by_norm[norm(b.get("name", ""))].append(b)

    # candidate source pages: all pages from any Confluence-related books and from already created root-books
    source_pages = pages
    pages_by_norm: Dict[str, List[dict]] = defaultdict(list)
    for p in source_pages:
        pages_by_norm[norm(p.get("name", ""))].append(p)

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "books_created": [],
        "chapters_created": [],
        "chapters_updated": [],
        "pages_moved": [],
        "chapter_content_pages_deleted": [],
        "unmatched_confluence_pages": [],
        "errors": [],
    }

    # Ensure top-level books
    book_for_root: Dict[str, dict] = {}
    for root_id in top_level:
        root_title = page_map[root_id].get("title", "Untitled")
        bucket = books_by_norm.get(norm(root_title), [])
        if bucket:
            book = bucket[0]
        else:
            try:
                book = bs.create_book(root_title, description=f"Auto-structure from Confluence root '{root_title}'")
                report["books_created"].append({"id": int(book["id"]), "name": book.get("name")})
                books_by_norm[norm(root_title)].append(book)
            except Exception as exc:
                report["errors"].append({"action": "create_book", "title": root_title, "error": str(exc)})
                continue
        book_for_root[root_id] = book

    # Refresh chapters/pages after creating books
    chapters = get_all(bs, "/api/chapters")
    pages = get_all(bs, "/api/pages")
    pages_by_norm = defaultdict(list)
    for p in pages:
        pages_by_norm[norm(p.get("name", ""))].append(p)

    used_page_ids: set[int] = set()

    # Ensure chapters for depth=1 and attach optional chapter description from page content
    chapter_for_depth1: Dict[str, dict] = {}

    for pid, page in page_map.items():
        if depth[pid] != 1:
            continue
        chapter_title = page.get("title", "Untitled")
        root_id = find_root_ancestor(pid, parent, depth)
        target_book = book_for_root.get(root_id)
        if not target_book:
            continue

        target_book_id = int(target_book["id"])

        existing = None
        for ch in chapters:
            if int(ch.get("book_id", -1)) == target_book_id and norm(ch.get("name", "")) == norm(chapter_title):
                existing = ch
                break

        if existing is None:
            try:
                existing = bs.create_chapter(target_book_id, chapter_title, description="")
                report["chapters_created"].append(
                    {"id": int(existing["id"]), "name": existing.get("name"), "book_id": target_book_id}
                )
                chapters.append(existing)
            except Exception as exc:
                report["errors"].append({"action": "create_chapter", "title": chapter_title, "error": str(exc)})
                continue

        chapter_for_depth1[pid] = existing

        # optional: if there is a page with same title, fold content into chapter description and remove page
        aliases = [chapter_title]
        cand = choose_page_candidate(aliases, pages_by_norm, used_page_ids)
        if cand:
            cand_id = int(cand["id"])
            try:
                detail = bs._request("GET", f"/api/pages/{cand_id}")
                excerpt = text_excerpt_from_html((detail.get("raw_html") or detail.get("html") or ""), limit=900)
                # update chapter with short description
                bs._request(
                    "PUT",
                    f"/api/chapters/{existing['id']}",
                    {
                        "name": existing.get("name", chapter_title),
                        "book_id": target_book_id,
                        "description": excerpt,
                    },
                )
                report["chapters_updated"].append({"chapter_id": int(existing["id"]), "description_from_page_id": cand_id})

                # delete page so level-1 remains chapter only
                bs._request("DELETE", f"/api/pages/{cand_id}")
                report["chapter_content_pages_deleted"].append({"page_id": cand_id, "name": cand.get("name", "")})
                used_page_ids.add(cand_id)
            except Exception as exc:
                report["errors"].append({"action": "chapter_description_or_delete_page", "page_id": cand_id, "error": str(exc)})

    # Refresh page inventory after deletions
    pages = get_all(bs, "/api/pages")
    pages_by_norm = defaultdict(list)
    for p in pages:
        pages_by_norm[norm(p.get("name", ""))].append(p)

    # Move depth>=2 pages to their chapter in their root-book
    chapter_priority_counter: Dict[int, int] = defaultdict(lambda: 1)

    # process in BFS-ish order by depth then id for stable behavior
    ordered_ids = sorted([pid for pid in page_map.keys() if depth[pid] >= 2], key=lambda x: (depth[x], str(x)))

    for pid in ordered_ids:
        confluence_title = page_map[pid].get("title", "Untitled")
        root_id = find_root_ancestor(pid, parent, depth)
        first_level_id = find_first_level_ancestor(pid, parent, depth)

        if first_level_id is None:
            report["unmatched_confluence_pages"].append({"id": pid, "title": confluence_title, "reason": "no first-level ancestor"})
            continue

        chapter = chapter_for_depth1.get(first_level_id)
        if chapter is None:
            report["unmatched_confluence_pages"].append({"id": pid, "title": confluence_title, "reason": "chapter missing"})
            continue

        desired_name = desired_page_name(pid, page_map, parent, depth)

        aliases = [
            desired_name,
            confluence_title,
        ]

        # legacy trail alias from old migration style
        chain = []
        cur: Optional[str] = pid
        while cur is not None:
            chain.append(cur)
            cur = parent.get(cur)
        chain.reverse()
        if len(chain) >= 2:
            legacy_trail = " / ".join([page_map[x].get("title", "") for x in chain[1:]])
            aliases.append(legacy_trail)

        cand = choose_page_candidate(aliases, pages_by_norm, used_page_ids)
        if cand is None:
            report["unmatched_confluence_pages"].append({"id": pid, "title": confluence_title, "desired_name": desired_name})
            continue

        cand_id = int(cand["id"])
        used_page_ids.add(cand_id)

        try:
            detail = bs._request("GET", f"/api/pages/{cand_id}")
            html = detail.get("raw_html") or detail.get("html") or "<p></p>"
            priority = chapter_priority_counter[int(chapter["id"])]
            chapter_priority_counter[int(chapter["id"])] += 1

            bs._request(
                "PUT",
                f"/api/pages/{cand_id}",
                {
                    "name": desired_name,
                    "html": html,
                    "chapter_id": int(chapter["id"]),
                    "priority": priority,
                },
            )
            report["pages_moved"].append(
                {
                    "confluence_id": pid,
                    "from_page_id": cand_id,
                    "to_chapter_id": int(chapter["id"]),
                    "new_name": desired_name,
                    "priority": priority,
                }
            )
        except Exception as exc:
            report["errors"].append({"action": "move_page", "confluence_id": pid, "page_id": cand_id, "error": str(exc)})

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"BOOKS_CREATED={len(report['books_created'])}")
    print(f"CHAPTERS_CREATED={len(report['chapters_created'])}")
    print(f"PAGES_MOVED={len(report['pages_moved'])}")
    print(f"UNMATCHED={len(report['unmatched_confluence_pages'])}")
    print(f"ERRORS={len(report['errors'])}")
    print(f"REPORT={REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
