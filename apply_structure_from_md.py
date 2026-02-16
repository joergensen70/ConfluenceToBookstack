import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import requests

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, Migrator, load_config_from_env

MD_PATH = Path("confluence_structure_cs_auto.md")
REPORT_PATH = Path("apply_structure_from_md_report.json")
CREATE_MISSING_PAGES = True


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def get_all(bs: BookStackClient, endpoint: str, count: int = 500) -> List[dict]:
    items: List[dict] = []
    offset = 0
    while True:
        data = bs_request(bs, "GET", f"{endpoint}?count={count}&offset={offset}")
        batch = data.get("data", [])
        items.extend(batch)
        if len(batch) < count:
            break
        offset += count
    return items


def bs_request(bs: BookStackClient, method: str, path: str, json_data: Optional[dict] = None, retries: int = 6) -> dict:
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return bs._request(method, path, json_data)
        except requests.HTTPError as exc:
            last_exc = exc
            status = exc.response.status_code if exc.response is not None else None
            if status in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(2 * attempt, 10))
                continue
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(1)
                continue
            raise
    raise RuntimeError(f"BookStack request failed: {last_exc}")


def esc_cql(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def fetch_confluence_page_html(conf: ConfluenceClient, migrator: Migrator, space_key: str, title: str) -> Optional[str]:
    cql = f'space="{space_key}" and type=page and title="{esc_cql(title)}"'
    data = conf._get_json("/wiki/rest/api/content/search", {"cql": cql, "limit": 5, "expand": "body.storage,body.view"})
    hits = data.get("results", [])
    if not hits:
        return None

    page = hits[0]
    view_html = page.get("body", {}).get("view", {}).get("value", "")
    storage_html = page.get("body", {}).get("storage", {}).get("value", "")
    if view_html:
        html = view_html
    else:
        try:
            html = conf.convert_storage_to_view(storage_html)
        except Exception:
            html = storage_html

    html = migrator._normalize_html_links(html or "<p></p>")
    return html if html.strip() else "<p></p>"


def parse_md_structure(md_text: str) -> List[dict]:
    books: List[dict] = []
    current_book: Optional[dict] = None
    current_chapter: Optional[dict] = None
    current_space_key = ""

    for raw_line in md_text.splitlines():
        line = raw_line.rstrip("\n")

        if line.startswith("## Space `"):
            match = re.search(r"^## Space `([^`]+)`", line)
            current_space_key = match.group(1).strip() if match else ""
            current_book = None
            current_chapter = None
            continue

        if line.startswith("### Buch: "):
            title = line.replace("### Buch: ", "", 1).strip()
            current_book = {"title": title, "chapters": [], "space_key": current_space_key}
            books.append(current_book)
            current_chapter = None
            continue

        if current_book and line.startswith("- Chapter: "):
            chapter_part = line.replace("- Chapter: ", "", 1).strip()
            if chapter_part.startswith("**"):
                continue
            chapter_title = re.sub(r"\s*\(\*\*.*?\*\*\)\s*$", "", chapter_part).strip()
            current_chapter = {"title": chapter_title, "pages": []}
            current_book["chapters"].append(current_chapter)
            continue

        if current_chapter and line.startswith("  - Seite: "):
            page_title = line.replace("  - Seite: ", "", 1).strip()
            if page_title:
                current_chapter["pages"].append(page_title)
            continue

    return books


def choose_page_candidate(candidates: List[dict], target_book_id: int, target_chapter_id: int, used_ids: set[int]) -> Optional[dict]:
    ranked = []
    for candidate in candidates:
        page_id = int(candidate.get("id"))
        if page_id in used_ids:
            continue
        chapter_id = candidate.get("chapter_id")
        chapter_id = int(chapter_id) if chapter_id is not None else None
        book_id = candidate.get("book_id")
        book_id = int(book_id) if book_id is not None else None

        if chapter_id == target_chapter_id:
            score = 0
        elif book_id == target_book_id:
            score = 1
        else:
            score = 2
        ranked.append((score, page_id, candidate))

    if not ranked:
        return None
    ranked.sort(key=lambda x: (x[0], x[1]))
    return ranked[0][2]


def main() -> int:
    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    if not MD_PATH.exists():
        raise RuntimeError(f"MD-Datei nicht gefunden: {MD_PATH}")

    target_books = parse_md_structure(MD_PATH.read_text(encoding="utf-8"))
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    migrator = Migrator(cfg, dry_run=False)

    books = get_all(bs, "/api/books")
    chapters = get_all(bs, "/api/chapters")
    pages = get_all(bs, "/api/pages")

    books_by_norm: Dict[str, List[dict]] = {}
    for book in books:
        books_by_norm.setdefault(norm(book.get("name", "")), []).append(book)

    report = {
        "books_target": len(target_books),
        "chapters_target": sum(len(book["chapters"]) for book in target_books),
        "pages_target": sum(len(ch["pages"]) for book in target_books for ch in book["chapters"]),
        "books_created": [],
        "chapters_created": [],
        "chapters_updated": [],
        "pages_moved": [],
        "pages_created": [],
        "pages_missing": [],
        "errors": [],
        "verification": {},
    }

    target_book_ids_by_norm: Dict[str, int] = {}

    for target_book in target_books:
        book_title = target_book["title"]
        book_norm = norm(book_title)
        bucket = books_by_norm.get(book_norm, [])

        if bucket:
            book = bucket[0]
        else:
            try:
                book = bs_request(bs, "POST", "/api/books", {"name": book_title, "description": "Auto-created from confluence_structure_cs_auto.md"})
                report["books_created"].append({"id": int(book["id"]), "name": book.get("name")})
                books_by_norm.setdefault(book_norm, []).append(book)
            except Exception as exc:
                report["errors"].append({"action": "create_book", "book": book_title, "error": str(exc)})
                continue

        target_book_id = int(book["id"])
        target_book_ids_by_norm[book_norm] = target_book_id

        chapter_priority = 1
        chapters = get_all(bs, "/api/chapters")
        chapters_in_book = [ch for ch in chapters if int(ch.get("book_id", -1)) == target_book_id]
        chapters_by_norm = {norm(ch.get("name", "")): ch for ch in chapters_in_book}

        used_page_ids: set[int] = set()

        for target_chapter in target_book["chapters"]:
            chapter_title = target_chapter["title"]
            chapter_norm = norm(chapter_title)

            chapter = chapters_by_norm.get(chapter_norm)
            if not chapter:
                try:
                    chapter = bs_request(bs, "POST", "/api/chapters", {"book_id": target_book_id, "name": chapter_title, "description": ""})
                    report["chapters_created"].append(
                        {"id": int(chapter["id"]), "book_id": target_book_id, "name": chapter.get("name")}
                    )
                    chapters_by_norm[chapter_norm] = chapter
                except Exception as exc:
                    report["errors"].append(
                        {"action": "create_chapter", "book": book_title, "chapter": chapter_title, "error": str(exc)}
                    )
                    chapter_priority += 1
                    continue

            chapter_id = int(chapter["id"])

            try:
                bs_request(
                    bs,
                    "PUT",
                    f"/api/chapters/{chapter_id}",
                    {"name": chapter.get("name", chapter_title), "book_id": target_book_id, "priority": chapter_priority},
                )
                report["chapters_updated"].append(
                    {"id": chapter_id, "book_id": target_book_id, "name": chapter.get("name", chapter_title), "priority": chapter_priority}
                )
            except Exception as exc:
                report["errors"].append(
                    {
                        "action": "update_chapter_priority",
                        "book": book_title,
                        "chapter": chapter_title,
                        "chapter_id": chapter_id,
                        "error": str(exc),
                    }
                )

            page_priority = 1
            for target_page_title in target_chapter["pages"]:
                try:
                    pages = get_all(bs, "/api/pages")
                    candidates = [p for p in pages if norm(p.get("name", "")) == norm(target_page_title)]
                    candidate = choose_page_candidate(candidates, target_book_id, chapter_id, used_page_ids)

                    if candidate is None:
                        if CREATE_MISSING_PAGES:
                            space_key = target_book.get("space_key") or cfg.confluence_space_key
                            html = fetch_confluence_page_html(conf, migrator, str(space_key), target_page_title)
                            if html is None:
                                html = f"<p>Platzhalterseite, erzeugt aus Strukturdatei: {target_page_title}</p>"
                            created = bs_request(
                                bs,
                                "POST",
                                "/api/pages",
                                {"name": target_page_title, "html": html, "chapter_id": chapter_id},
                            )
                            created_id = int(created["id"])
                            used_page_ids.add(created_id)
                            report["pages_created"].append(
                                {
                                    "id": created_id,
                                    "name": created.get("name"),
                                    "book_id": target_book_id,
                                    "chapter_id": chapter_id,
                                    "priority": page_priority,
                                }
                            )
                        else:
                            report["pages_missing"].append(
                                {"book": book_title, "chapter": chapter_title, "page": target_page_title}
                            )
                        page_priority += 1
                        continue

                    page_id = int(candidate["id"])
                    used_page_ids.add(page_id)
                    try:
                        detail = bs_request(bs, "GET", f"/api/pages/{page_id}")
                        page_name = detail.get("name") or target_page_title
                        page_html = detail.get("raw_html") or detail.get("html") or "<p></p>"

                        bs_request(
                            bs,
                            "PUT",
                            f"/api/pages/{page_id}",
                            {
                                "name": page_name,
                                "html": page_html,
                                "chapter_id": chapter_id,
                                "priority": page_priority,
                            },
                        )
                    except requests.HTTPError as move_exc:
                        status = move_exc.response.status_code if move_exc.response is not None else None
                        if status in (404, 500, 502, 503, 504):
                            space_key = target_book.get("space_key") or cfg.confluence_space_key
                            fallback_html = fetch_confluence_page_html(conf, migrator, str(space_key), target_page_title)
                            if fallback_html is None:
                                raise
                            created = bs_request(
                                bs,
                                "POST",
                                "/api/pages",
                                {"name": target_page_title, "html": fallback_html, "chapter_id": chapter_id},
                            )
                            page_id = int(created["id"])
                            page_name = created.get("name") or target_page_title
                        else:
                            raise
                    report["pages_moved"].append(
                        {
                            "id": page_id,
                            "name": page_name,
                            "book_id": target_book_id,
                            "chapter_id": chapter_id,
                            "priority": page_priority,
                        }
                    )
                except Exception as exc:
                    report["errors"].append(
                        {
                            "action": "move_or_create_page",
                            "book": book_title,
                            "chapter": chapter_title,
                            "page": target_page_title,
                            "error": str(exc),
                        }
                    )
                page_priority += 1

            chapter_priority += 1

    # Verification pass
    books = get_all(bs, "/api/books")
    chapters = get_all(bs, "/api/chapters")
    pages = get_all(bs, "/api/pages")

    books_map = {norm(book.get("name", "")): book for book in books}
    chapter_lookup: Dict[tuple[int, str], dict] = {}
    for chapter in chapters:
        chapter_lookup[(int(chapter.get("book_id", -1)), norm(chapter.get("name", "")))] = chapter

    page_lookup: Dict[tuple[int, str], List[dict]] = {}
    for page in pages:
        chapter_id = page.get("chapter_id")
        if chapter_id is None:
            continue
        key = (int(chapter_id), norm(page.get("name", "")))
        page_lookup.setdefault(key, []).append(page)

    missing_books = []
    missing_chapters = []
    missing_pages = []

    for target_book in target_books:
        book_title = target_book["title"]
        book = books_map.get(norm(book_title))
        if not book:
            missing_books.append(book_title)
            continue

        book_id = int(book["id"])
        for target_chapter in target_book["chapters"]:
            chapter_title = target_chapter["title"]
            chapter = chapter_lookup.get((book_id, norm(chapter_title)))
            if not chapter:
                missing_chapters.append({"book": book_title, "chapter": chapter_title})
                continue

            chapter_id = int(chapter["id"])
            for target_page_title in target_chapter["pages"]:
                if not page_lookup.get((chapter_id, norm(target_page_title))):
                    missing_pages.append(
                        {"book": book_title, "chapter": chapter_title, "page": target_page_title}
                    )

    report["verification"] = {
        "missing_books": missing_books,
        "missing_chapters": missing_chapters,
        "missing_pages": missing_pages,
        "ok": len(missing_books) == 0 and len(missing_chapters) == 0 and len(missing_pages) == 0,
    }

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"TARGET_BOOKS={report['books_target']}")
    print(f"TARGET_CHAPTERS={report['chapters_target']}")
    print(f"TARGET_PAGES={report['pages_target']}")
    print(f"BOOKS_CREATED={len(report['books_created'])}")
    print(f"CHAPTERS_CREATED={len(report['chapters_created'])}")
    print(f"PAGES_MOVED={len(report['pages_moved'])}")
    print(f"PAGES_CREATED={len(report['pages_created'])}")
    print(f"ERRORS={len(report['errors'])}")
    print(f"VERIFY_OK={report['verification']['ok']}")
    print(f"REPORT={REPORT_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
