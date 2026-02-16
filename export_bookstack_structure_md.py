from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "migration_overview_bookstack_cn.md"


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


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " und ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class BookStackSimpleClient:
    def __init__(self, base_url: str, token_id: str, token_secret: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {token_id}:{token_secret}",
                "Accept": "application/json",
            }
        )

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def get_all(self, endpoint: str, count: int = 500) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0

        for _ in range(200):
            data = self._get_json(endpoint, {"count": count, "offset": offset})
            batch = data.get("data", [])
            if not batch:
                break

            items.extend(batch)
            if len(batch) < count:
                break
            offset += len(batch)

        return items


def choose_target_book(books: list[dict[str, Any]], space_name: str, explicit_book_name: str | None) -> dict[str, Any]:
    if explicit_book_name:
        for book in books:
            if (book.get("name") or "") == explicit_book_name:
                return book
        raise RuntimeError(f"Book nicht gefunden (BOOKSTACK_TARGET_BOOK): {explicit_book_name}")

    expected_prefix = os.getenv("BOOKSTACK_BOOK_PREFIX", "Confluence - ").strip()
    expected_name = f"{expected_prefix}{space_name}".strip()

    for book in books:
        if (book.get("name") or "") == expected_name:
            return book

    expected_norm = norm(expected_name)
    for book in books:
        if norm(book.get("name") or "") == expected_norm:
            return book

    space_token = norm(space_name)
    for book in books:
        book_norm = norm(book.get("name") or "")
        if "confluence" in book_norm and space_token and space_token in book_norm:
            return book

    raise RuntimeError(
        "Kein passendes Ziel-Book gefunden. Setze BOOKSTACK_TARGET_BOOK in .env für eine exakte Auswahl."
    )


def main() -> int:
    load_dotenv(ROOT / ".env")

    required = ["BOOKSTACK_BASE_URL", "BOOKSTACK_TOKEN_ID", "BOOKSTACK_TOKEN_SECRET"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Fehlende Variablen: {', '.join(missing)}")

    space_key = os.getenv("CONFLUENCE_SPACE_KEY", "CN")
    space_name = os.getenv("CONFLUENCE_SPACE_NAME", "Computer & Netzwerk")
    explicit_book_name = os.getenv("BOOKSTACK_TARGET_BOOK")

    client = BookStackSimpleClient(
        os.environ["BOOKSTACK_BASE_URL"],
        os.environ["BOOKSTACK_TOKEN_ID"],
        os.environ["BOOKSTACK_TOKEN_SECRET"],
    )

    books = client.get_all("/api/books")
    target_book = choose_target_book(books, space_name, explicit_book_name)
    target_book_id = int(target_book["id"])
    target_book_name = target_book.get("name") or f"Book {target_book_id}"

    chapters = [c for c in client.get_all("/api/chapters") if int(c.get("book_id", -1)) == target_book_id]
    pages = [p for p in client.get_all("/api/pages") if int(p.get("book_id", -1)) == target_book_id]

    chapters.sort(key=lambda item: (int(item.get("priority") or 0), (item.get("name") or "").lower()))
    pages.sort(key=lambda item: (int(item.get("priority") or 0), (item.get("name") or "").lower()))

    pages_by_chapter: dict[int, list[dict[str, Any]]] = {}
    root_pages: list[dict[str, Any]] = []
    for page in pages:
        chapter_id = int(page.get("chapter_id") or 0)
        if chapter_id <= 0:
            root_pages.append(page)
            continue
        pages_by_chapter.setdefault(chapter_id, []).append(page)

    top_level_items: list[dict[str, Any]] = []
    for page in root_pages:
        top_level_items.append(
            {
                "type": "root_page",
                "name": page.get("name") or "Untitled",
                "priority": int(page.get("priority") or 0),
                "chapter_count": 0,
                "pages_under_chapter": 0,
            }
        )

    for chapter in chapters:
        chapter_id = int(chapter["id"])
        chapter_pages = pages_by_chapter.get(chapter_id, [])
        top_level_items.append(
            {
                "type": "chapter",
                "name": chapter.get("name") or "Untitled",
                "priority": int(chapter.get("priority") or 0),
                "chapter_count": 1,
                "pages_under_chapter": len(chapter_pages),
                "chapter": chapter,
                "chapter_pages": chapter_pages,
            }
        )

    top_level_items.sort(key=lambda item: (item["priority"], (item["name"] or "").lower()))

    lines: list[str] = []
    lines.append("# BookStack Migrationsübersicht")
    lines.append("")
    lines.append(f"- Space-Key: `{space_key}`")
    lines.append(f"- Space-Name: `{space_name}`")
    lines.append(f"- Ziel-Book in BookStack: `{target_book_name}`")
    lines.append("")
    lines.append("## Statistik")
    lines.append("")
    lines.append(f"- Gesamtseiten im Book: **{len(pages)}**")
    lines.append(f"- Top-Level-Elemente: **{len(top_level_items)}**")
    lines.append(f"- Chapter (direkt im Book): **{len(chapters)}**")
    lines.append(f"- Seiten ohne Chapter: **{len(root_pages)}**")
    lines.append(f"- Seiten in Chaptern: **{len(pages) - len(root_pages)}**")
    lines.append("")
    lines.append("## Top-Level Übersicht")
    lines.append("")

    if not top_level_items:
        lines.append("- Keine Top-Level-Knoten erkannt.")
    else:
        for item in top_level_items:
            lines.append(
                f"- {item['name']} (Chapter: {item['chapter_count']}, Seiten unterhalb Chapter: {item['pages_under_chapter']})"
            )

    lines.append("")
    lines.append("## Strukturzuordnung")
    lines.append("")
    lines.append("Format: Buch (oberste Ebene) → Chapter (Ebene darunter) → Seite (darunter)")
    lines.append("")

    if not top_level_items:
        lines.append("- Keine Strukturzuordnung möglich.")
    else:
        for item in top_level_items:
            lines.append(f"### Buch: {item['name']}")

            if item["type"] == "root_page":
                lines.append("- _(Keine Chapter)_")
                lines.append("")
                continue

            chapter = item["chapter"]
            chapter_pages = item["chapter_pages"]
            lines.append(f"- Chapter: {chapter.get('name') or 'Untitled'}")

            if not chapter_pages:
                lines.append("  - _(Keine Seiten)_")
            else:
                for page in chapter_pages:
                    lines.append(f"  - Seite: {page.get('name') or 'Untitled'}")

            lines.append("")

    lines.append("")
    lines.append("> Hinweis: Diese Übersicht wird auf Basis der aktuellen BookStack-Struktur erstellt.")
    lines.append("")

    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")

    print(f"OUTPUT={OUTPUT_FILE}")
    print(f"TARGET_BOOK_ID={target_book_id}")
    print(f"TARGET_BOOK_NAME={target_book_name}")
    print(f"TOTAL_PAGES={len(pages)}")
    print(f"TOTAL_TOP_LEVEL={len(top_level_items)}")
    print(f"TOTAL_CHAPTERS={len(chapters)}")
    print(f"TOTAL_ROOT_PAGES={len(root_pages)}")
    print(f"TOTAL_CHAPTER_PAGES={len(pages) - len(root_pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())