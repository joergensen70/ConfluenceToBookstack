#!/usr/bin/env python3
import argparse
import base64
import html
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import requests


@dataclass
class Config:
    confluence_base_url: str
    confluence_email: str
    confluence_api_token: str
    confluence_space_key: str
    bookstack_base_url: str
    bookstack_token_id: str
    bookstack_token_secret: str
    book_name_prefix: str


class ConfluenceClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        auth = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
        self.session.headers.update({"Authorization": f"Basic {auth}", "Accept": "application/json"})

    def _get_json(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def get_space_name(self, space_key: str) -> str:
        data = self._get_json(f"/wiki/rest/api/space/{space_key}")
        return data.get("name") or space_key

    def resolve_space_key(self, requested_space_key: str) -> str:
        requested = (requested_space_key or "").strip()
        if not requested:
            raise RuntimeError("Leerer Space-Key angegeben")

        alias_map = {
            "cs": "CN",
            "cn": "CN",
            "auto": "AUTO",
        }

        candidates = [requested, requested.upper(), requested.lower()]
        mapped = alias_map.get(requested.lower())
        if mapped:
            candidates.append(mapped)

        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                self._get_json(f"/wiki/rest/api/space/{candidate}")
                return candidate
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 404:
                    continue
                raise

        raise RuntimeError(f"Confluence-Space nicht gefunden: {requested_space_key}")

    def list_pages_in_space(self, space_key: str) -> List[dict]:
        pages: List[dict] = []
        limit = 50
        cursor: Optional[str] = None
        seen_cursors: set[str] = set()
        seen_page_ids: set[str] = set()
        safety_counter = 0
        max_iterations = 2000

        while True:
            safety_counter += 1
            if safety_counter > max_iterations:
                raise RuntimeError(
                    f"Abbruch beim Seitenabruf: zu viele Iterationen ({max_iterations}) für Space '{space_key}'."
                )

            params = {
                "cql": f'space="{space_key}" and type=page',
                "expand": "body.storage,body.view,ancestors",
                "limit": limit,
            }
            if cursor:
                params["cursor"] = cursor
            else:
                params["start"] = 0

            data = self._get_json("/wiki/rest/api/content/search", params=params)
            batch = data.get("results", [])
            if not batch:
                break

            new_items = 0
            for item in batch:
                page_id = str(item.get("id", ""))
                if page_id and page_id in seen_page_ids:
                    continue
                if page_id:
                    seen_page_ids.add(page_id)
                pages.append(item)
                new_items += 1

            if new_items == 0:
                break

            links = data.get("_links", {})
            next_link = links.get("next") if isinstance(links, dict) else None
            if not next_link:
                break

            next_cursor: Optional[str] = None
            try:
                parsed = urlparse(next_link)
                q = parse_qs(parsed.query)
                if "cursor" in q and q["cursor"]:
                    next_cursor = q["cursor"][0]
            except (ValueError, TypeError, KeyError):
                next_cursor = None

            if not next_cursor:
                break

            if next_cursor in seen_cursors:
                break

            seen_cursors.add(next_cursor)
            cursor = next_cursor

        return pages

    def convert_storage_to_view(self, storage_html: str) -> str:
        url = f"{self.base_url}/wiki/rest/api/contentbody/convert/view"
        payload = {"value": storage_html, "representation": "storage"}
        response = self.session.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data.get("value", storage_html)

    def download_binary(self, url: str) -> bytes:
        final_url = url if url.startswith("http") else urljoin(self.base_url, url)
        response = self.session.get(final_url, timeout=120)
        if response.status_code in (401, 403):
            fallback = self._download_via_attachment_api(final_url)
            if fallback is not None:
                return fallback
        response.raise_for_status()
        return response.content

    def _download_via_attachment_api(self, image_url: str) -> Optional[bytes]:
        decoded_url = html.unescape(image_url)
        match = re.search(r"/download/(?:thumbnails|attachments)/(\d+)/([^/?]+)", decoded_url)
        if not match:
            return None

        page_id, filename = match.group(1), match.group(2)
        list_url = f"{self.base_url}/wiki/rest/api/content/{page_id}/child/attachment"
        list_response = self.session.get(list_url, params={"filename": filename, "limit": 25}, timeout=60)
        if list_response.status_code >= 400:
            return None

        data = list_response.json()
        results = data.get("results", [])
        if not results:
            return None

        attachment_id = results[0].get("id")
        if not attachment_id:
            return None

        download_url = f"{self.base_url}/wiki/rest/api/content/{page_id}/child/attachment/{attachment_id}/download"
        download_response = self.session.get(download_url, timeout=120)
        if download_response.status_code >= 400:
            return None
        return download_response.content


class BookStackClient:
    def __init__(self, base_url: str, token_id: str, token_secret: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {token_id}:{token_secret}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, json_data: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        max_attempts = 6

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.session.request(method=method, url=url, json=json_data, timeout=60)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                    print(
                        f"[BookStack] Retry {attempt}/{max_attempts} ({response.status_code}) {method} {path}",
                        flush=True,
                    )
                    time.sleep(min(2 * attempt, 10))
                    continue

                response.raise_for_status()
                if response.text.strip():
                    return response.json()
                return {}
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= max_attempts:
                    raise
                print(
                    f"[BookStack] Retry {attempt}/{max_attempts} ({type(exc).__name__}) {method} {path}",
                    flush=True,
                )
                time.sleep(min(2 * attempt, 10))

        raise RuntimeError(f"BookStack request failed after {max_attempts} attempts: {method} {path}")

    def find_book_by_name(self, name: str) -> Optional[dict]:
        data = self._request("GET", "/api/books?count=500")
        for item in data.get("data", []):
            if item.get("name") == name:
                return item
        return None

    def _trim_name(self, name: str, context: str) -> str:
        cleaned = (name or "").strip()
        if not cleaned:
            cleaned = "Untitled"
        if len(cleaned) <= 255:
            return cleaned
        trimmed = cleaned[:252] + "..."
        print(f"[BookStack] Name gekuerzt ({context}): {cleaned[:80]}...", flush=True)
        return trimmed

    def create_book(self, name: str, description: str = "") -> dict:
        safe_name = self._trim_name(name, "book")
        return self._request("POST", "/api/books", {"name": safe_name, "description": description})

    def create_chapter(self, book_id: int, name: str, description: str = "") -> dict:
        safe_name = self._trim_name(name, "chapter")
        return self._request("POST", "/api/chapters", {"book_id": book_id, "name": safe_name, "description": description})

    def create_page(self, name: str, html: str, book_id: Optional[int] = None, chapter_id: Optional[int] = None) -> dict:
        safe_html = html if html and html.strip() else "<p></p>"
        safe_name = self._trim_name(name, "page")
        payload = {"name": safe_name, "html": safe_html}
        if chapter_id is not None:
            payload["chapter_id"] = chapter_id
        elif book_id is not None:
            payload["book_id"] = book_id
        else:
            raise ValueError("Either book_id or chapter_id must be set")
        return self._request("POST", "/api/pages", payload)

    def update_page_html(self, page_id: int, name: str, html: str) -> dict:
        if not html or not html.strip():
            return {}

        safe_name = self._trim_name(name, "page")

        try:
            return self._request("PUT", f"/api/pages/{page_id}", {"name": safe_name, "html": html})
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status != 422:
                raise

            url = f"{self.base_url}/api/pages/{page_id}"
            headers = {"Authorization": self.session.headers["Authorization"], "Accept": "application/json"}
            response = requests.put(url, headers=headers, data={"name": safe_name, "html": html}, timeout=60)
            response.raise_for_status()
            if response.text.strip():
                return response.json()
            return {}

    def upload_gallery_image(self, page_id: int, filename: str, binary: bytes) -> str:
        url = f"{self.base_url}/api/image-gallery"
        headers = {"Authorization": self.session.headers["Authorization"], "Accept": "application/json"}
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(binary)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as file_obj:
                files = {"image": (filename, file_obj)}
                data = {"uploaded_to": str(page_id), "type": "gallery", "name": filename}
                response = requests.post(url, headers=headers, files=files, data=data, timeout=120)
                response.raise_for_status()
                result = response.json()
                return result["url"]
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def check_access(self) -> dict:
        try:
            return self._request("GET", "/api/system")
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 404:
                data = self._request("GET", "/api/books?count=1")
                total = data.get("total") if isinstance(data, dict) else None
                return {"app_name": "BookStack", "books_total": total}
            raise

    def list_books(self, count: int = 500) -> List[dict]:
        return self._request("GET", f"/api/books?count={count}").get("data", [])

    def list_shelves(self, count: int = 500) -> List[dict]:
        return self._request("GET", f"/api/shelves?count={count}").get("data", [])

    def find_shelf_by_name(self, name: str) -> Optional[dict]:
        for shelf in self.list_shelves():
            if shelf.get("name") == name:
                return shelf
        return None

    def create_shelf(self, name: str, description: str = "", books: Optional[List[int]] = None) -> dict:
        payload: dict = {"name": name, "description": description}
        if books is not None:
            payload["books"] = books
        return self._request("POST", "/api/shelves", payload)

    def update_shelf_books(self, shelf_id: int, name: str, books: List[int]) -> dict:
        payload = {"name": name, "books": books}
        return self._request("PUT", f"/api/shelves/{shelf_id}", payload)

    def get_shelf_detail(self, shelf_id: int) -> dict:
        return self._request("GET", f"/api/shelves/{shelf_id}")

    def ensure_shelf_books(self, shelf_name: str, books_to_include: List[int], description: str = "") -> dict:
        normalized = sorted({int(book_id) for book_id in books_to_include if int(book_id) > 0})
        shelf = self.find_shelf_by_name(shelf_name)
        if shelf is None:
            return self.create_shelf(shelf_name, description=description, books=normalized)
        return self.update_shelf_books(int(shelf["id"]), shelf.get("name", shelf_name), normalized)


class Migrator:
    IMG_SRC_PATTERN = re.compile(r'(<img\b[^>]*?src=["\'])([^"\']+)(["\'][^>]*>)', flags=re.IGNORECASE)

    def __init__(
        self,
        config: Config,
        space_key: Optional[str] = None,
        dry_run: bool = False,
        auto_confirm: bool = False,
        overview_only: bool = False,
        overview_file: Optional[str] = None,
    ):
        self.config = config
        self.space_key = space_key or config.confluence_space_key
        self.dry_run = dry_run
        self.auto_confirm = auto_confirm
        self.overview_only = overview_only
        default_overview = f"migration_overview_{self.space_key.lower()}.md"
        self.overview_file = Path(overview_file) if overview_file else Path(default_overview)
        self.conf = ConfluenceClient(config.confluence_base_url, config.confluence_email, config.confluence_api_token)
        self.bs = BookStackClient(config.bookstack_base_url, config.bookstack_token_id, config.bookstack_token_secret)

    def run(self) -> dict:
        space_name = self.conf.get_space_name(self.space_key)
        book_name = f"{self.config.book_name_prefix}{space_name}" if self.config.book_name_prefix else space_name
        book_name = self.bs._trim_name(book_name, "book")
        summary = {
            "space_key": self.space_key,
            "space_name": space_name,
            "book_id": -1,
            "book_name": book_name,
            "book_ids": [],
            "pages_total": 0,
        }

        print(f"[1/7] Lade Seiten aus Space '{self.space_key}'...")
        pages = self.conf.list_pages_in_space(self.space_key)
        if not pages:
            print("Keine Seiten gefunden.")
            return summary
        print(f"Gefunden: {len(pages)} Seiten")
        summary["pages_total"] = len(pages)

        page_map, children, top_level = self._build_structure(pages, space_name)
        overview_text = self._build_overview_markdown(space_name, book_name, page_map, children, top_level)
        self.overview_file.write_text(overview_text, encoding="utf-8")

        print(f"[2/7] Übersicht erstellt: {self.overview_file}")
        stats = self._compute_structure_stats(page_map, children, top_level)
        print(
            f"  Statistik: Bücher={stats['books']} | Chapter={stats['chapters']} | "
            f"Seiten(ab Ebene 3)={stats['pages_level_3_plus']}"
        )

        if self.overview_only:
            print("Nur Übersicht erzeugt (--overview-only). Keine Migration ausgeführt.")
            return summary

        if not self.dry_run and not self.auto_confirm:
            if not sys.stdin.isatty():
                print("Nicht-interaktive Sitzung erkannt. Bitte mit --yes bestätigen oder --overview-only nutzen.")
                return summary

            answer = input("Übersicht prüfen und Migration starten? [y/N]: ").strip().lower()
            if answer not in ("y", "yes", "j", "ja"):
                print("Abbruch auf Benutzerwunsch nach Übersicht.")
                return summary

        print("[3/7] Ermittele/erstelle Books pro Top-Level...")
        created_pages: List[Tuple[str, str, int, int]] = []
        book_ids: List[int] = []

        for root_id in top_level:
            root_page = page_map[root_id]
            root_title = root_page.get("title", "Untitled")
            has_children = len(children[root_id]) > 0
            print(f"  Book: {root_title} (Kinder: {len(children[root_id])})", flush=True)

            if self.dry_run:
                book = {"id": -1, "name": root_title}
            else:
                book = self.bs.find_book_by_name(root_title) or self.bs.create_book(
                    root_title,
                    description=f"Automatisch migriert aus Confluence Space {self.space_key}",
                )
                book_ids.append(int(book["id"]))

            if has_children:
                for chapter_id in children[root_id]:
                    chapter_title = page_map[chapter_id].get("title", "Untitled")
                    if self.dry_run:
                        bs_chapter_id = -1
                    else:
                        chapter = self.bs.create_chapter(book["id"], chapter_title)
                        bs_chapter_id = int(chapter["id"])
                        print(f"    Kapitel erstellt: {chapter_title} -> {bs_chapter_id}", flush=True)

                    descendants = self._collect_descendants(chapter_id, children)
                    for child_id in descendants:
                        if child_id == chapter_id:
                            continue
                        trail = self._build_trail_under_chapter(child_id, page_map, chapter_id)
                        created_pages.append((child_id, trail, bs_chapter_id, int(book["id"])))
            else:
                created_pages.append((root_id, root_title, -1, int(book["id"])))

        summary["book_ids"] = book_ids

        print(f"[5/7] Übertrage Inhalte ({len(created_pages)} Seiten)...")
        confluence_to_bookstack_page: Dict[str, int] = {}

        for idx, (conf_page_id, target_title, chapter_id, book_id) in enumerate(created_pages, start=1):
            page_data = page_map[conf_page_id]
            view_html = page_data.get("body", {}).get("view", {}).get("value", "")
            storage_html = page_data.get("body", {}).get("storage", {}).get("value", "")

            if view_html:
                rendered_html = view_html
            else:
                try:
                    rendered_html = self.conf.convert_storage_to_view(storage_html)
                except Exception:
                    rendered_html = storage_html

            rendered_html = self._normalize_html_links(rendered_html)
            if not rendered_html or not rendered_html.strip():
                rendered_html = "<p></p>"

            safe_title = self.bs._trim_name(target_title, "page")

            if self.dry_run:
                print(f"  [dry-run] ({idx}/{len(created_pages)}) {safe_title}")
                continue

            if chapter_id > 0:
                try:
                    created = self.bs.create_page(safe_title, rendered_html, chapter_id=chapter_id)
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else "?"
                    print(f"  [WARN] Seite übersprungen (HTTP {status}): {safe_title}", flush=True)
                    continue
            else:
                try:
                    created = self.bs.create_page(safe_title, rendered_html, book_id=book_id)
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else "?"
                    print(f"  [WARN] Seite übersprungen (HTTP {status}): {safe_title}", flush=True)
                    continue

            bs_page_id = created["id"]
            confluence_to_bookstack_page[conf_page_id] = bs_page_id

            html_with_local_images, image_count = self._migrate_images(rendered_html, bs_page_id)
            if image_count > 0 and html_with_local_images and html_with_local_images.strip():
                self.bs.update_page_html(bs_page_id, safe_title, html_with_local_images)

            print(f"  ({idx}/{len(created_pages)}) {safe_title} -> Seite {bs_page_id}, Bilder: {image_count}")

        print("[6/7] Interne Links umschreiben...")
        if not self.dry_run:
            self._rewrite_internal_links(page_map, confluence_to_bookstack_page)

        print("[7/7] Fertig.")
        if self.dry_run:
            print("Dry-run beendet. Keine Änderungen in BookStack vorgenommen.")
        return summary

    def _build_trail_under_chapter(self, page_id: str, page_map: Dict[str, dict], chapter_id: str) -> str:
        page = page_map[page_id]
        ancestors = page.get("ancestors", []) or []
        titles: List[str] = []
        for anc in ancestors:
            anc_id = anc.get("id")
            if anc_id in page_map:
                anc_title = page_map[anc_id].get("title")
                if anc_title:
                    titles.append(anc_title)
        titles.append(page.get("title", "Untitled"))

        chapter_title = page_map.get(chapter_id, {}).get("title", "")
        if chapter_title and chapter_title in titles:
            idx = titles.index(chapter_title)
            titles = titles[idx + 1 :]

        if len(titles) <= 1:
            return titles[0]
        return " / ".join(titles)

    def _normalize_title(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    def _build_structure(
        self,
        pages: List[dict],
        space_name: str,
    ) -> Tuple[Dict[str, dict], Dict[str, List[str]], List[str]]:
        page_map = {p["id"]: p for p in pages}
        children: Dict[str, List[str]] = {p["id"]: [] for p in pages}
        top_level_raw: List[str] = []

        for page in pages:
            parent_id = self._find_parent_in_space(page, page_map)
            if parent_id:
                children[parent_id].append(page["id"])
            else:
                top_level_raw.append(page["id"])

        top_level = list(top_level_raw)
        if len(top_level_raw) == 1:
            root_id = top_level_raw[0]
            root_title = self._normalize_title(page_map[root_id].get("title", ""))
            if root_title in {
                self._normalize_title(space_name),
                self._normalize_title(self.config.confluence_space_key),
            } and children[root_id]:
                top_level = list(children[root_id])

        return page_map, children, top_level

    def _compute_structure_stats(
        self,
        page_map: Dict[str, dict],
        children: Dict[str, List[str]],
        top_level: List[str],
    ) -> Dict[str, int]:
        chapter_count = 0
        pages_level_3_plus = 0

        for book_id in top_level:
            chapter_ids = children.get(book_id, [])
            chapter_count += len(chapter_ids)
            for chapter_id in chapter_ids:
                descendants = self._collect_descendants(chapter_id, children)
                pages_level_3_plus += max(0, len(descendants) - 1)

        return {
            "total_pages": len(page_map),
            "books": len(top_level),
            "chapters": chapter_count,
            "pages_level_3_plus": pages_level_3_plus,
        }

    def _build_overview_markdown(
        self,
        space_name: str,
        book_name: str,
        page_map: Dict[str, dict],
        children: Dict[str, List[str]],
        top_level: List[str],
    ) -> str:
        stats = self._compute_structure_stats(page_map, children, top_level)
        lines: List[str] = []

        lines.append("# Confluence Migrationsübersicht")
        lines.append("")
        lines.append(f"- Space-Key: `{self.space_key}`")
        lines.append(f"- Space-Name: `{space_name}`")
        lines.append(f"- Ziel-Book in BookStack: `{book_name}`")
        lines.append("")
        lines.append("## Statistik")
        lines.append("")
        lines.append(f"- Gesamtseiten im Space: **{stats['total_pages']}**")
        lines.append(f"- Bücher (Top-Level): **{stats['books']}**")
        lines.append(f"- Chapter (Ebene 2): **{stats['chapters']}**")
        lines.append(f"- Seiten (ab Ebene 3): **{stats['pages_level_3_plus']}**")
        lines.append("")
        lines.append("## Top-Level Übersicht")
        lines.append("")

        if not top_level:
            lines.append("- Keine Top-Level-Knoten erkannt.")
        else:
            for book_id in top_level:
                book_title = page_map[book_id].get("title", "Untitled")
                chapter_ids = children.get(book_id, [])
                page_count = 0
                for chapter_id in chapter_ids:
                    descendants = self._collect_descendants(chapter_id, children)
                    page_count += max(0, len(descendants) - 1)
                lines.append(
                    f"- {book_title} (Chapter: {len(chapter_ids)}, Seiten unterhalb Chapter: {page_count})"
                )

        lines.append("")
        lines.append("## Strukturzuordnung")
        lines.append("")
        lines.append("Format: Buch (oberste Ebene) → Chapter (Ebene darunter) → Seite (darunter)")
        lines.append("")

        def add_pages_recursive(node_id: str, depth: int) -> int:
            count = 0
            for child_id in children.get(node_id, []):
                page_title = page_map[child_id].get("title", "Untitled")
                indent = "  " * depth
                lines.append(f"{indent}- Seite: {page_title}")
                count += 1
                count += add_pages_recursive(child_id, depth + 1)
            return count

        if not top_level:
            lines.append("- Keine Strukturzuordnung möglich.")
        else:
            for book_id in top_level:
                book_title = page_map[book_id].get("title", "Untitled")
                chapter_ids = children.get(book_id, [])

                lines.append(f"### Buch: {book_title}")
                if not chapter_ids:
                    lines.append("- _(Keine Chapter)_")
                    lines.append("")
                    continue

                for chapter_id in chapter_ids:
                    chapter_title = page_map[chapter_id].get("title", "Untitled")
                    lines.append(f"- Chapter: {chapter_title}")
                    page_count = add_pages_recursive(chapter_id, 1)
                    if page_count == 0:
                        lines.append("  - _(Keine Seiten)_")

                lines.append("")

        lines.append("")
        lines.append("> Hinweis: Diese Übersicht wird vor jeder Migration erstellt. Bitte erst prüfen, dann bestätigen.")
        lines.append("")
        return "\n".join(lines)

    def _find_parent_in_space(self, page: dict, page_map: Dict[str, dict]) -> Optional[str]:
        ancestors = page.get("ancestors", []) or []
        for anc in reversed(ancestors):
            anc_id = anc.get("id")
            if anc_id in page_map:
                return anc_id
        return None

    def _collect_descendants(self, root_id: str, children: Dict[str, List[str]]) -> List[str]:
        order = [root_id]
        stack = list(children[root_id])
        while stack:
            node = stack.pop(0)
            order.append(node)
            stack[0:0] = children[node]
        return order

    def _build_trail_title(self, page_id: str, page_map: Dict[str, dict], root_id: str) -> str:
        page = page_map[page_id]
        ancestors = page.get("ancestors", []) or []
        titles: List[str] = []
        for anc in ancestors:
            anc_id = anc.get("id")
            if anc_id in page_map:
                anc_title = page_map[anc_id].get("title")
                if anc_title:
                    titles.append(anc_title)
        titles.append(page.get("title", "Untitled"))

        root_title = page_map.get(root_id, {}).get("title", "")
        if root_title and root_title in titles:
            root_index = titles.index(root_title)
            titles = titles[root_index + 1 :]

        if len(titles) <= 1:
            return titles[0]
        return " / ".join(titles)

    def _normalize_html_links(self, html: str) -> str:
        def repl(match: re.Match) -> str:
            prefix, src, suffix = match.groups()
            if src.startswith("http://") or src.startswith("https://") or src.startswith("data:"):
                return match.group(0)
            absolute = urljoin(self.config.confluence_base_url, src)
            return f"{prefix}{absolute}{suffix}"

        return self.IMG_SRC_PATTERN.sub(repl, html)

    def _migrate_images(self, html: str, bookstack_page_id: int) -> Tuple[str, int]:
        replacements: Dict[str, str] = {}
        unique_sources = []

        for _, src, _ in self.IMG_SRC_PATTERN.findall(html):
            if src not in replacements and src not in unique_sources:
                unique_sources.append(src)

        migrated = 0
        for src in unique_sources:
            if src.startswith("data:"):
                continue
            try:
                content = self.conf.download_binary(src)
                filename = Path(src.split("?")[0]).name or f"image_{migrated + 1}.bin"
                new_url = self.bs.upload_gallery_image(bookstack_page_id, filename, content)
                replacements[src] = new_url
                migrated += 1
                print(f"    Bild migriert ({migrated}/{len(unique_sources)}): {filename}", flush=True)
            except Exception as exc:
                print(f"    Bild konnte nicht übertragen werden ({src}): {exc}")

        if not replacements:
            return html, 0

        def repl(match: re.Match) -> str:
            prefix, src, suffix = match.groups()
            return f"{prefix}{replacements.get(src, src)}{suffix}"

        updated = self.IMG_SRC_PATTERN.sub(repl, html)
        return updated, migrated

    def _rewrite_internal_links(self, page_map: Dict[str, dict], conf_to_bs: Dict[str, int]) -> None:
        # Optionaler Schritt: Link-Rewrite ist stark abhängig vom Link-Format.
        # Hier nur Basis-Support für .../pages/{id}/... Links.
        link_pattern = re.compile(r'href=["\']([^"\']+/pages/(\\d+)[^"\']*)["\']', flags=re.IGNORECASE)

        for conf_id, bs_page_id in conf_to_bs.items():
            page = self.bs._request("GET", f"/api/pages/{bs_page_id}")
            name = page.get("name", "Untitled")
            html = page.get("raw_html") or page.get("html") or ""

            changed = False

            def repl(match: re.Match) -> str:
                nonlocal changed
                whole_url = match.group(1)
                target_id = match.group(2)
                if target_id in conf_to_bs:
                    changed = True
                    return f'href="{self.config.bookstack_base_url}/books/{page.get("book_slug", "")}/page/{conf_to_bs[target_id]}"'
                return f'href="{whole_url}"'

            new_html = link_pattern.sub(repl, html)
            if changed:
                self.bs.update_page_html(bs_page_id, name, new_html)


def load_config_from_env() -> Config:
    env_path = Path(".env")
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

    required = [
        "CONFLUENCE_BASE_URL",
        "CONFLUENCE_EMAIL",
        "CONFLUENCE_API_TOKEN",
        "CONFLUENCE_SPACE_KEY",
        "BOOKSTACK_BASE_URL",
        "BOOKSTACK_TOKEN_ID",
        "BOOKSTACK_TOKEN_SECRET",
    ]

    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Fehlende Umgebungsvariablen: {', '.join(missing)}")

    placeholder_patterns = {
        "CONFLUENCE_EMAIL": ["dein.name@beispiel.de", "example.com", "@beispiel.de"],
        "CONFLUENCE_API_TOKEN": ["atlassian_api_token", "changeme", "placeholder"],
        "CONFLUENCE_SPACE_KEY": ["DEIN_SPACE_KEY", "your_space_key", "space_key"],
        "BOOKSTACK_BASE_URL": ["dein-bookstack.example.com", "example.com"],
        "BOOKSTACK_TOKEN_ID": ["bookstack_token_id", "changeme", "placeholder"],
        "BOOKSTACK_TOKEN_SECRET": ["bookstack_token_secret", "changeme", "placeholder"],
    }

    placeholders_found: List[str] = []
    for key, tokens in placeholder_patterns.items():
        value = os.environ.get(key, "").strip().lower()
        if not value:
            continue
        if any(token in value for token in tokens):
            placeholders_found.append(key)

    if placeholders_found:
        raise RuntimeError(
            "Bitte ersetze Platzhalterwerte in .env für: "
            + ", ".join(placeholders_found)
            + "."
        )

    if not os.environ["CONFLUENCE_BASE_URL"].startswith("https://"):
        raise RuntimeError("CONFLUENCE_BASE_URL muss mit https:// beginnen.")

    if not os.environ["BOOKSTACK_BASE_URL"].startswith("https://"):
        raise RuntimeError("BOOKSTACK_BASE_URL muss mit https:// beginnen.")

    return Config(
        confluence_base_url=os.environ["CONFLUENCE_BASE_URL"],
        confluence_email=os.environ["CONFLUENCE_EMAIL"],
        confluence_api_token=os.environ["CONFLUENCE_API_TOKEN"],
        confluence_space_key=os.environ["CONFLUENCE_SPACE_KEY"],
        bookstack_base_url=os.environ["BOOKSTACK_BASE_URL"],
        bookstack_token_id=os.environ["BOOKSTACK_TOKEN_ID"],
        bookstack_token_secret=os.environ["BOOKSTACK_TOKEN_SECRET"],
        book_name_prefix=os.getenv("BOOKSTACK_BOOK_PREFIX", "Confluence - "),
    )


def _print_confluence_auth_hints(status: str, body: str) -> None:
    print("  Hinweise Confluence:")
    if str(status) == "401":
        print("   - API-Token oder E-Mail ist vermutlich falsch.")
        print("   - Prüfe, ob der Token als Atlassian API Token erstellt wurde.")
    elif str(status) == "403":
        print("   - Der User hat keinen Zugriff auf den angegebenen Space.")
        print("   - Prüfe CONFLUENCE_SPACE_KEY auf Tippfehler.")
        print("   - Prüfe, ob der Account in Confluence für diesen Space berechtigt ist.")
    elif str(status) == "404":
        print("   - Space oder URL nicht gefunden.")
        print("   - Prüfe CONFLUENCE_BASE_URL und CONFLUENCE_SPACE_KEY.")
    elif str(status) == "429":
        print("   - Rate-Limit erreicht. Bitte später erneut versuchen.")
    else:
        print("   - Prüfe Base-URL, Token, E-Mail und Space-Rechte.")
    if "cannot access confluence" in body.lower():
        print("   - Atlassian meldet fehlende Berechtigung für Confluence-Zugriff.")


def _print_bookstack_auth_hints(status: str, body: str) -> None:
    print("  Hinweise BookStack:")
    if str(status) == "401":
        print("   - Token ID/Secret ist ungültig oder falsch gesetzt.")
        print("   - Prüfe Authorization-Token in .env.")
    elif str(status) == "403":
        print("   - Der API-User hat nicht genug Rechte.")
        print("   - In BookStack muss die Rolle die Berechtigung 'Access System API' haben.")
    elif str(status) == "404":
        print("   - API-Endpunkt nicht gefunden.")
        print("   - Prüfe BOOKSTACK_BASE_URL (ohne zusätzlichen Pfad wie /books).")
    elif str(status) == "429":
        print("   - Rate-Limit erreicht. Bitte später erneut versuchen.")
    else:
        print("   - Prüfe URL, Token und API-Berechtigungen.")
    if "no authorization token" in body.lower():
        print("   - Authorization Header fehlt oder ist falsch formatiert.")


def check_credentials(config: Config, debug_auth: bool = False) -> int:
    print("[Auth-Check] Prüfe Confluence-Zugriff...")
    try:
        conf = ConfluenceClient(config.confluence_base_url, config.confluence_email, config.confluence_api_token)
        space_name = conf.get_space_name(config.confluence_space_key)
        print(f"  OK: Confluence Space erreichbar ({config.confluence_space_key} -> {space_name})")
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        body = exc.response.text[:300] if exc.response is not None else ""
        print(f"  FEHLER: Confluence-Zugriff fehlgeschlagen (HTTP {status}) {body}")
        if debug_auth:
            _print_confluence_auth_hints(str(status), body)
        return 10
    except Exception as exc:
        print(f"  FEHLER: Confluence-Zugriff fehlgeschlagen ({exc})")
        if debug_auth:
            print("  Hinweise Confluence:")
            print("   - Prüfe Netzwerk, DNS, Proxy/VPN und HTTPS-URL.")
        return 10

    print("[Auth-Check] Prüfe BookStack-Zugriff...")
    try:
        bs = BookStackClient(config.bookstack_base_url, config.bookstack_token_id, config.bookstack_token_secret)
        system_info = bs.check_access()
        instance_name = system_info.get("app_name") or system_info.get("name") or "BookStack"
        print(f"  OK: BookStack API erreichbar ({instance_name})")
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        body = exc.response.text[:300] if exc.response is not None else ""
        print(f"  FEHLER: BookStack-Zugriff fehlgeschlagen (HTTP {status}) {body}")
        if debug_auth:
            _print_bookstack_auth_hints(str(status), body)
        return 11
    except Exception as exc:
        print(f"  FEHLER: BookStack-Zugriff fehlgeschlagen ({exc})")
        if debug_auth:
            print("  Hinweise BookStack:")
            print("   - Prüfe Netzwerk, DNS, TLS-Zertifikat und API-Erreichbarkeit.")
        return 11

    print("[Auth-Check] Beide Verbindungen sind OK.")
    return 0


def parse_space_keys(value: str) -> List[str]:
    parts = [part.strip() for part in (value or "").split(",")]
    return [part for part in parts if part]


def pick_overview_file(base_value: str, total_spaces: int, index: int, resolved_space_key: str) -> Optional[str]:
    if not base_value:
        return None
    if total_spaces <= 1:
        return base_value

    base = Path(base_value)
    stem = base.stem
    suffix = base.suffix or ".md"
    return str(base.with_name(f"{stem}_{resolved_space_key.lower()}{suffix}"))


def get_all_bookstack_items(bs: BookStackClient, endpoint: str, count: int = 500) -> List[dict]:
    items: List[dict] = []
    offset = 0
    while True:
        data = bs._request("GET", f"{endpoint}?count={count}&offset={offset}")
        batch = data.get("data", [])
        items.extend(batch)
        if len(batch) < count:
            break
        offset += count
    return items


def normalize_book_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*-\s*", "-", text)
    return text


def build_expected_book_names(prefix: str, space_name: str) -> List[str]:
    raw_prefix = prefix or ""
    space = space_name or ""
    candidates = []
    candidates.append(f"{raw_prefix}{space}")
    candidates.append(f"{raw_prefix.rstrip()} {space}")
    candidates.append(f"{raw_prefix.strip()} {space}")
    return [c.strip() for c in candidates if c and c.strip()]


def check_migration_completeness(config: Config, resolved_spaces: List[Tuple[str, str, str]], shelf_name: str) -> int:
    conf = ConfluenceClient(config.confluence_base_url, config.confluence_email, config.confluence_api_token)
    bs = BookStackClient(config.bookstack_base_url, config.bookstack_token_id, config.bookstack_token_secret)

    shelf = bs.find_shelf_by_name(shelf_name)
    if not shelf:
        shelf = bs.ensure_shelf_books(
            shelf_name,
            [],
            description="Isoliertes Shelf für Confluence-Migrationen",
        )
        print(f"[Check] Shelf angelegt: {shelf.get('name', shelf_name)} (ID {shelf.get('id')})")

    shelf_detail = bs.get_shelf_detail(int(shelf["id"]))
    shelf_books = shelf_detail.get("books", [])
    shelf_book_ids = {int(book.get("id", -1)) for book in shelf_books if int(book.get("id", -1)) > 0}

    all_books = [book for book in bs.list_books() if int(book.get("id", -1)) in shelf_book_ids]
    all_chapters = [
        chapter
        for chapter in get_all_bookstack_items(bs, "/api/chapters")
        if int(chapter.get("book_id", -1)) in shelf_book_ids
    ]
    all_pages = [
        page
        for page in get_all_bookstack_items(bs, "/api/pages")
        if int(page.get("book_id", -1)) in shelf_book_ids
    ]

    has_error = False
    report: Dict[str, object] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "spaces": [],
        "ok": False,
    }

    print(f"[Check] Prüfe Vollständigkeit je Space (Shelf: {shelf_detail.get('name', shelf_name)})...")
    for _, resolved_space, resolved_name in resolved_spaces:
        expected_space_pages = conf.list_pages_in_space(resolved_space)
        run_cfg = Config(
            confluence_base_url=config.confluence_base_url,
            confluence_email=config.confluence_email,
            confluence_api_token=config.confluence_api_token,
            confluence_space_key=resolved_space,
            bookstack_base_url=config.bookstack_base_url,
            bookstack_token_id=config.bookstack_token_id,
            bookstack_token_secret=config.bookstack_token_secret,
            book_name_prefix=config.book_name_prefix,
        )
        inspector = Migrator(run_cfg, space_key=resolved_space, dry_run=True, auto_confirm=True, overview_only=True)
        page_map, children, top_level = inspector._build_structure(expected_space_pages, resolved_name)

        for root_id in top_level:
            root_title = page_map[root_id].get("title", "Untitled")
            root_candidates = [normalize_book_name(root_title)]
            target_book = None
            for book in all_books:
                book_name = book.get("name", "")
                if normalize_book_name(book_name) in root_candidates:
                    target_book = book
                    break

            expected_chapters = len(children.get(root_id, []))
            expected_direct_pages = 1 if expected_chapters == 0 else 0
            expected_pages = 0
            for chapter_id in children.get(root_id, []):
                descendants = inspector._collect_descendants(chapter_id, children)
                expected_pages += max(0, len(descendants) - 1)
            if expected_chapters == 0:
                expected_pages = 1

            if not target_book:
                has_error = True
                report["spaces"].append(
                    {
                        "space_key": resolved_space,
                        "space_name": resolved_name,
                        "book_name": root_title,
                        "book_candidates": [root_title],
                        "book_found": False,
                        "expected_pages": expected_pages,
                        "expected_chapters": expected_chapters,
                        "expected_direct_pages": expected_direct_pages,
                    }
                )
                print(
                    f"  [FEHLT] {resolved_space}: Book '{root_title}' nicht gefunden "
                    f"(Confluence Seiten: {expected_pages})"
                )
                continue

            book_id = int(target_book["id"])
            chapters_in_book = [chapter for chapter in all_chapters if int(chapter.get("book_id", -1)) == book_id]
            chapter_ids = {int(chapter.get("id", -1)) for chapter in chapters_in_book}
            pages_in_book = [page for page in all_pages if int(page.get("book_id", -1)) == book_id]

            direct_pages = [page for page in pages_in_book if page.get("chapter_id") is None]
            chapter_pages = [
                page
                for page in pages_in_book
                if page.get("chapter_id") is not None and int(page.get("chapter_id", -1)) in chapter_ids
            ]

            ok_pages = len(pages_in_book) == expected_pages
            ok_chapters = len(chapters_in_book) == expected_chapters
            ok_direct_pages = len(direct_pages) == expected_direct_pages
            is_ok = ok_pages and ok_chapters and ok_direct_pages

            status = "OK" if is_ok else "DIFF"
            print(
                f"  [{status}] {resolved_space} -> Book {book_id} '{target_book.get('name')}' | "
                f"Pages Soll/Ist: {expected_pages}/{len(pages_in_book)} | "
                f"Chapters Soll/Ist: {expected_chapters}/{len(chapters_in_book)} | "
                f"Direktseiten Soll/Ist: {expected_direct_pages}/{len(direct_pages)} | "
                f"Chapter-Seiten Ist: {len(chapter_pages)}"
            )

            if not is_ok:
                has_error = True

            report["spaces"].append(
                {
                    "space_key": resolved_space,
                    "space_name": resolved_name,
                    "book_name": root_title,
                    "book_found": True,
                    "book_id": book_id,
                    "expected_pages": expected_pages,
                    "actual_pages": len(pages_in_book),
                    "expected_chapters": expected_chapters,
                    "actual_chapters": len(chapters_in_book),
                    "expected_direct_pages": expected_direct_pages,
                    "actual_direct_pages": len(direct_pages),
                    "actual_chapter_pages": len(chapter_pages),
                    "ok": is_ok,
                }
            )

    report["ok"] = not has_error
    Path("migration_check_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if has_error:
        print("[Check] FEHLER: Mindestens ein Space ist unvollständig oder strukturell abweichend.")
        return 4

    print("[Check] OK: Alle Spaces sind vollständig und strukturell konsistent migriert.")
    return 0


def parse_space_keys(value: str) -> List[str]:
    parts = [part.strip() for part in (value or "").split(",")]
    return [part for part in parts if part]


def main() -> int:
    parser = argparse.ArgumentParser(description="Confluence Cloud -> BookStack Migration (inkl. Bilder)")
    parser.add_argument("--dry-run", action="store_true", help="Nur Struktur prüfen, nichts in BookStack schreiben")
    parser.add_argument(
        "--check-credentials",
        action="store_true",
        help="Nur Zugangsdaten prüfen (Confluence + BookStack), keine Migration ausführen",
    )
    parser.add_argument(
        "--debug-auth",
        action="store_true",
        help="Gibt bei Auth-Fehlern zusätzliche Ursachen-Hinweise aus (mit --check-credentials nutzbar)",
    )
    parser.add_argument(
        "--overview-only",
        action="store_true",
        help="Nur Confluence-Übersicht + Statistik erstellen, keine Migration starten",
    )
    parser.add_argument(
        "--overview-file",
        default="",
        help="Pfad für die Übersichtsdatei (Default: migration_overview_<space>.md)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Migration ohne interaktive Rückfrage nach der Übersicht starten",
    )
    parser.add_argument(
        "--spaces",
        default=os.getenv("CONFLUENCE_SPACE_KEYS", ""),
        help="Kommagetrennte Liste von Space-Keys, z. B. AUTO,CS. Fallback: CONFLUENCE_SPACE_KEY",
    )
    parser.add_argument(
        "--shelf-name",
        default=os.getenv("BOOKSTACK_SHELF_NAME", "Confluence Migration (isolated)"),
        help="Name des Ziel-Shelves für alle migrierten Bücher",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Nur Vollständigkeit/Struktur je Space prüfen, keine Migration ausführen",
    )
    args = parser.parse_args()

    try:
        cfg = load_config_from_env()
    except Exception as exc:
        print(exc)
        return 1

    requested_spaces = parse_space_keys(args.spaces)
    if not requested_spaces:
        requested_spaces = [cfg.confluence_space_key]

    try:
        conf_resolver = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
        resolved_spaces: List[Tuple[str, str, str]] = []
        for requested_space in requested_spaces:
            resolved_space = conf_resolver.resolve_space_key(requested_space)
            resolved_name = conf_resolver.get_space_name(resolved_space)
            resolved_spaces.append((requested_space, resolved_space, resolved_name))
    except Exception as exc:
        print(f"Fehler bei Space-Auflösung: {exc}")
        return 1

    if args.check_credentials or args.debug_auth:
        print("[Auth-Check] Aufgelöste Spaces:")
        for requested_space, resolved_space, resolved_name in resolved_spaces:
            alias = f" (angefragt als {requested_space})" if requested_space.lower() != resolved_space.lower() else ""
            print(f"  - {resolved_space}: {resolved_name}{alias}")
        return check_credentials(cfg, debug_auth=args.debug_auth)

    if args.check_only:
        return check_migration_completeness(cfg, resolved_spaces, args.shelf_name)

    migrated_book_ids: List[int] = []
    try:
        for idx, (requested_space, resolved_space, resolved_name) in enumerate(resolved_spaces, start=1):
            print(f"\n=== Space {idx}/{len(resolved_spaces)}: {resolved_space} ({resolved_name}) ===")
            if requested_space.lower() != resolved_space.lower():
                print(f"Alias aufgelöst: {requested_space} -> {resolved_space}")

            run_cfg = Config(
                confluence_base_url=cfg.confluence_base_url,
                confluence_email=cfg.confluence_email,
                confluence_api_token=cfg.confluence_api_token,
                confluence_space_key=resolved_space,
                bookstack_base_url=cfg.bookstack_base_url,
                bookstack_token_id=cfg.bookstack_token_id,
                bookstack_token_secret=cfg.bookstack_token_secret,
                book_name_prefix=cfg.book_name_prefix,
            )
            overview_path = pick_overview_file(args.overview_file, len(resolved_spaces), idx, resolved_space)
            result = Migrator(
                run_cfg,
                space_key=resolved_space,
                dry_run=args.dry_run,
                auto_confirm=args.yes,
                overview_only=args.overview_only,
                overview_file=overview_path,
            ).run()

            book_ids = result.get("book_ids") or []
            migrated_book_ids.extend([int(bid) for bid in book_ids if int(bid) > 0])

            if not args.dry_run and not args.overview_only and migrated_book_ids:
                bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
                shelf = bs.ensure_shelf_books(
                    args.shelf_name,
                    migrated_book_ids,
                    description="Isoliertes Shelf für Confluence-Migrationen",
                )
                print(
                    f"Shelf synchronisiert: {shelf.get('name', args.shelf_name)} "
                    f"(ID {shelf.get('id')}, Bücher: {len(migrated_book_ids)})"
                )
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response else "?"
        text = exc.response.text[:500] if exc.response is not None else ""
        print(f"HTTP-Fehler ({status}): {text}")
        return 2
    except Exception as exc:
        print(f"Fehler: {exc}")
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
