import json
import os
import re
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, load_config_from_env

REPORT = Path("apply_structure_retry_report.json")


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


def bs_request(bs: BookStackClient, method: str, path: str, json_data: Optional[dict] = None, retries: int = 5) -> dict:
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return bs._request(method, path, json_data)
        except requests.HTTPError as exc:
            last_exc = exc
            status = exc.response.status_code if exc.response is not None else None
            if status == 429 and attempt < retries:
                time.sleep(2 * attempt)
                continue
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(1)
                continue
            raise
    raise RuntimeError(f"BookStack request failed: {last_exc}")


def get_all(bs: BookStackClient, endpoint: str, count: int = 500) -> List[dict]:
    return bs_request(bs, "GET", f"{endpoint}?count={count}").get("data", [])


def page_html(detail: dict) -> str:
    html = detail.get("raw_html") or detail.get("html") or "<p></p>"
    return html if html and html.strip() else "<p></p>"


def build_tree(conf_pages: List[dict]):
    page_map = {p["id"]: p for p in conf_pages}
    children: Dict[str, List[str]] = {p["id"]: [] for p in conf_pages}
    parent: Dict[str, Optional[str]] = {p["id"]: None for p in conf_pages}
    top: List[str] = []

    for p in conf_pages:
        pid = p["id"]
        parent_id = None
        for anc in reversed(p.get("ancestors", []) or []):
            aid = anc.get("id")
            if aid in page_map:
                parent_id = aid
                break
        parent[pid] = parent_id
        if parent_id:
            children[parent_id].append(pid)
        else:
            top.append(pid)

    depth: Dict[str, int] = {}

    def d(pid: str) -> int:
        if pid in depth:
            return depth[pid]
        pp = parent.get(pid)
        if pp is None:
            depth[pid] = 0
        else:
            depth[pid] = d(pp) + 1
        return depth[pid]

    for pid in page_map:
        d(pid)

    return page_map, children, parent, top, depth


def root_of(pid: str, parent: Dict[str, Optional[str]]) -> str:
    cur = pid
    while parent.get(cur) is not None:
        cur = parent[cur]  # type: ignore[index]
    return cur


def first_level_of(pid: str, parent: Dict[str, Optional[str]], depth: Dict[str, int]) -> Optional[str]:
    cur = pid
    while True:
        pp = parent.get(cur)
        if pp is None:
            return None
        if depth.get(pp, 0) == 1:
            return pp
        cur = pp


def confluence_trail(pid: str, page_map: Dict[str, dict], parent: Dict[str, Optional[str]], from_depth: int) -> str:
    chain = []
    cur: Optional[str] = pid
    while cur is not None:
        chain.append(cur)
        cur = parent.get(cur)
    chain.reverse()
    titles = []
    for idx, cid in enumerate(chain):
        if idx >= from_depth:
            titles.append(page_map[cid].get("title", ""))
    return " / ".join(titles).strip()


def choose_candidate(aliases: List[str], index: Dict[str, List[dict]], used: set[int]) -> Optional[dict]:
    for alias in aliases:
        key = norm(alias)
        for item in index.get(key, []):
            pid = int(item.get("id", -1))
            if pid not in used:
                return item
    return None


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "books_created": [],
        "chapters_created": [],
        "pages_moved": [],
        "unmatched": [],
        "errors": [],
    }

    try:
        conf_pages = conf.list_pages_in_space(cfg.confluence_space_key)
        page_map, children, parent, top, depth = build_tree(conf_pages)

        books = get_all(bs, "/api/books")
        chapters = get_all(bs, "/api/chapters")
        pages = get_all(bs, "/api/pages")

        books_by_norm = defaultdict(list)
        for b in books:
            books_by_norm[norm(b.get("name", ""))].append(b)

        # ensure books for each top-level page
        book_for_root: Dict[str, dict] = {}
        for rid in top:
            title = page_map[rid].get("title", "Untitled")
            pool = books_by_norm.get(norm(title), [])
            if pool:
                b = pool[0]
            else:
                b = bs_request(bs, "POST", "/api/books", {"name": title, "description": "Auto-created from Confluence top-level"})
                report["books_created"].append({"id": int(b["id"]), "name": b.get("name")})
                books_by_norm[norm(title)].append(b)
            book_for_root[rid] = b

        # refresh chapters/pages
        chapters = get_all(bs, "/api/chapters")
        pages = get_all(bs, "/api/pages")

        # ensure chapters for depth=1
        chapter_for_depth1: Dict[str, dict] = {}
        for pid, pdata in page_map.items():
            if depth[pid] != 1:
                continue
            title = pdata.get("title", "Untitled")
            rid = root_of(pid, parent)
            b = book_for_root[rid]
            bid = int(b["id"])

            existing = None
            for ch in chapters:
                if int(ch.get("book_id", -1)) == bid and norm(ch.get("name", "")) == norm(title):
                    existing = ch
                    break
            if existing is None:
                existing = bs_request(bs, "POST", "/api/chapters", {"book_id": bid, "name": title, "description": ""})
                report["chapters_created"].append({"id": int(existing["id"]), "book_id": bid, "name": title})
                chapters.append(existing)
            chapter_for_depth1[pid] = existing

        # move pages depth>=2 to chapters
        pages = get_all(bs, "/api/pages")
        index = defaultdict(list)
        for p in pages:
            index[norm(p.get("name", ""))].append(p)

        used: set[int] = set()
        prio_by_ch: Dict[int, int] = defaultdict(lambda: 1)

        items = sorted([pid for pid in page_map if depth[pid] >= 2], key=lambda x: (depth[x], str(x)))
        for pid in items:
            title = page_map[pid].get("title", "Untitled")
            d = depth[pid]
            first = first_level_of(pid, parent, depth)
            if first is None:
                report["unmatched"].append({"confluence_id": pid, "title": title, "reason": "no first-level"})
                continue

            ch = chapter_for_depth1.get(first)
            if ch is None:
                report["unmatched"].append({"confluence_id": pid, "title": title, "reason": "missing chapter"})
                continue

            desired = title if d == 2 else confluence_trail(pid, page_map, parent, from_depth=2)
            legacy = confluence_trail(pid, page_map, parent, from_depth=1)

            aliases = [desired, title, legacy]
            cand = choose_candidate(aliases, index, used)
            if cand is None:
                report["unmatched"].append({"confluence_id": pid, "title": title, "desired": desired})
                continue

            page_id = int(cand["id"])
            used.add(page_id)

            try:
                detail = bs_request(bs, "GET", f"/api/pages/{page_id}")
                html = page_html(detail)
                ch_id = int(ch["id"])
                prio = prio_by_ch[ch_id]
                prio_by_ch[ch_id] += 1

                bs_request(
                    bs,
                    "PUT",
                    f"/api/pages/{page_id}",
                    {
                        "name": desired,
                        "html": html,
                        "chapter_id": ch_id,
                        "priority": prio,
                    },
                )
                report["pages_moved"].append({"confluence_id": pid, "page_id": page_id, "chapter_id": ch_id, "new_name": desired})
            except Exception as exc:
                report["errors"].append(
                    {
                        "action": "move_page",
                        "confluence_id": pid,
                        "page_id": page_id,
                        "desired": desired,
                        "error": str(exc),
                    }
                )

    except Exception as exc:
        report["errors"].append({"fatal": str(exc)})

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"BOOKS_CREATED={len(report['books_created'])}")
    print(f"CHAPTERS_CREATED={len(report['chapters_created'])}")
    print(f"PAGES_MOVED={len(report['pages_moved'])}")
    print(f"UNMATCHED={len(report['unmatched'])}")
    print(f"ERRORS={len(report['errors'])}")
    print(f"REPORT={REPORT}")

    return 0 if len(report["errors"]) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
