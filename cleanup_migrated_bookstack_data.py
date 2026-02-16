from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parent
REPORT_FILE = ROOT / "bookstack_migration_cleanup_report.json"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class BookStackApi:
    def __init__(self, base_url: str, token_id: str, token_secret: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {token_id}:{token_secret}",
                "Accept": "application/json",
            }
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: int = 90,
        retries: int = 5,
    ) -> requests.Response:
        last_exc: Exception | None = None
        backoff = 2.0
        for _ in range(retries):
            try:
                response = self.session.request(
                    method,
                    f"{self.base_url}{endpoint}",
                    params=params,
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exc = exc
                import time

                time.sleep(backoff)
                backoff = min(backoff * 2.0, 20.0)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Unerwarteter Fehler bei API-Anfrage")

    def get_all(self, endpoint: str, count: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        for _ in range(300):
            response = self._request(
                "GET",
                endpoint,
                params={"count": count, "offset": offset},
                timeout=60,
                retries=6,
            )
            batch = response.json().get("data", [])
            if not batch:
                break
            items.extend(batch)
            if len(batch) < count:
                break
            offset += len(batch)
        return items

    def get(self, endpoint: str) -> dict[str, Any]:
        response = self._request("GET", endpoint, timeout=60, retries=6)
        return response.json()

    def put(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("PUT", endpoint, payload=payload, timeout=60, retries=6)
        if response.text.strip():
            return response.json()
        return {}

    def delete(self, endpoint: str) -> None:
        self._request("DELETE", endpoint, timeout=60, retries=6)


def main() -> int:
    load_dotenv(ROOT / ".env")

    required = ["BOOKSTACK_BASE_URL", "BOOKSTACK_TOKEN_ID", "BOOKSTACK_TOKEN_SECRET"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Fehlende Variablen: {', '.join(missing)}")

    api = BookStackApi(
        os.environ["BOOKSTACK_BASE_URL"],
        os.environ["BOOKSTACK_TOKEN_ID"],
        os.environ["BOOKSTACK_TOKEN_SECRET"],
    )

    report: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scope": {
            "shelf_prefix": "Confluence Migration",
            "book_prefix": "Confluence -",
        },
        "candidates": {
            "shelves": [],
            "books": [],
            "chapters": 0,
            "pages": 0,
        },
        "deleted": {
            "pages": [],
            "chapters": [],
            "books": [],
        },
        "updated_shelves": [],
        "errors": [],
        "remaining": {
            "books": [],
            "chapters": 0,
            "pages": 0,
        },
    }

    books = api.get_all("/api/books")
    chapters = api.get_all("/api/chapters")
    pages = api.get_all("/api/pages")
    shelves = api.get_all("/api/shelves")

    target_book_ids: set[int] = set()
    candidate_shelves: list[dict[str, Any]] = []

    for shelf in shelves:
        shelf_name = shelf.get("name") or ""
        if shelf_name.startswith("Confluence Migration"):
            candidate_shelves.append({"id": int(shelf["id"]), "name": shelf_name})
            try:
                detail = api.get(f"/api/shelves/{int(shelf['id'])}")
                for book in detail.get("books", []):
                    book_id = int(book.get("id", -1))
                    if book_id > 0:
                        target_book_ids.add(book_id)
            except Exception as exc:
                report["errors"].append(
                    {
                        "action": "read_shelf",
                        "shelf_id": int(shelf["id"]),
                        "error": str(exc),
                    }
                )

    for book in books:
        name = (book.get("name") or "").strip()
        if name.startswith("Confluence -"):
            target_book_ids.add(int(book["id"]))

    target_books = [book for book in books if int(book.get("id", -1)) in target_book_ids]
    target_chapters = [chapter for chapter in chapters if int(chapter.get("book_id", -1)) in target_book_ids]
    target_pages = [page for page in pages if int(page.get("book_id", -1)) in target_book_ids]

    report["candidates"]["shelves"] = candidate_shelves
    report["candidates"]["books"] = [
        {"id": int(book["id"]), "name": book.get("name", "")} for book in sorted(target_books, key=lambda x: int(x["id"]))
    ]
    report["candidates"]["chapters"] = len(target_chapters)
    report["candidates"]["pages"] = len(target_pages)

    for shelf in candidate_shelves:
        try:
            detail = api.get(f"/api/shelves/{shelf['id']}")
            existing_books = detail.get("books", [])
            keep_ids = [int(book.get("id", -1)) for book in existing_books if int(book.get("id", -1)) not in target_book_ids]
            keep_ids = [book_id for book_id in keep_ids if book_id > 0]
            api.put(f"/api/shelves/{shelf['id']}", {"name": detail.get("name", shelf["name"]), "books": keep_ids})
            report["updated_shelves"].append(
                {
                    "shelf_id": shelf["id"],
                    "name": detail.get("name", shelf["name"]),
                    "remaining_books": len(keep_ids),
                }
            )
        except Exception as exc:
            report["errors"].append(
                {
                    "action": "update_shelf_books",
                    "shelf_id": shelf["id"],
                    "error": str(exc),
                }
            )

    for page in sorted(target_pages, key=lambda item: int(item.get("id", 0)), reverse=True):
        page_id = int(page["id"])
        try:
            api.delete(f"/api/pages/{page_id}")
            report["deleted"]["pages"].append({"id": page_id, "name": page.get("name", "")})
        except Exception as exc:
            report["errors"].append({"action": "delete_page", "page_id": page_id, "error": str(exc)})

    chapters_after_pages = api.get_all("/api/chapters")
    target_chapter_ids = {
        int(chapter["id"])
        for chapter in chapters_after_pages
        if int(chapter.get("book_id", -1)) in target_book_ids
    }

    for chapter_id in sorted(target_chapter_ids, reverse=True):
        chapter_name = ""
        for chapter in chapters_after_pages:
            if int(chapter.get("id", -1)) == chapter_id:
                chapter_name = chapter.get("name", "")
                break
        try:
            api.delete(f"/api/chapters/{chapter_id}")
            report["deleted"]["chapters"].append({"id": chapter_id, "name": chapter_name})
        except Exception as exc:
            report["errors"].append({"action": "delete_chapter", "chapter_id": chapter_id, "error": str(exc)})

    for book in sorted(target_books, key=lambda item: int(item.get("id", 0)), reverse=True):
        book_id = int(book["id"])
        try:
            api.delete(f"/api/books/{book_id}")
            report["deleted"]["books"].append({"id": book_id, "name": book.get("name", "")})
        except Exception as exc:
            report["errors"].append({"action": "delete_book", "book_id": book_id, "error": str(exc)})

    books_final = api.get_all("/api/books")
    chapters_final = api.get_all("/api/chapters")
    pages_final = api.get_all("/api/pages")

    remaining_books = [
        {"id": int(book["id"]), "name": book.get("name", "")}
        for book in books_final
        if int(book.get("id", -1)) in target_book_ids or (book.get("name") or "").startswith("Confluence -")
    ]
    remaining_chapters = [chapter for chapter in chapters_final if int(chapter.get("book_id", -1)) in target_book_ids]
    remaining_pages = [page for page in pages_final if int(page.get("book_id", -1)) in target_book_ids]

    report["remaining"]["books"] = sorted(remaining_books, key=lambda x: x["id"])
    report["remaining"]["chapters"] = len(remaining_chapters)
    report["remaining"]["pages"] = len(remaining_pages)

    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"REPORT={REPORT_FILE}")
    print(f"CANDIDATE_BOOKS={len(report['candidates']['books'])}")
    print(f"CANDIDATE_CHAPTERS={report['candidates']['chapters']}")
    print(f"CANDIDATE_PAGES={report['candidates']['pages']}")
    print(f"DELETED_BOOKS={len(report['deleted']['books'])}")
    print(f"DELETED_CHAPTERS={len(report['deleted']['chapters'])}")
    print(f"DELETED_PAGES={len(report['deleted']['pages'])}")
    print(f"REMAINING_BOOKS={len(report['remaining']['books'])}")
    print(f"REMAINING_CHAPTERS={report['remaining']['chapters']}")
    print(f"REMAINING_PAGES={report['remaining']['pages']}")
    print(f"ERRORS={len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())