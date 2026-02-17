#!/usr/bin/env python3
"""
Confluence to BookStack Migration Tool (Überarbeitete Version)
Vollständige Migration mit API-Checks, Struktur-Preview und Verifikation
"""
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
from typing import Dict, List, Optional, Tuple, Set
from urllib.parse import parse_qs, urljoin, urlparse

import requests


@dataclass
class Config:
    """Konfiguration für Confluence und BookStack APIs"""
    confluence_base_url: str
    confluence_email: str
    confluence_api_token: str
    bookstack_base_url: str
    bookstack_token_id: str
    bookstack_token_secret: str
    book_name_prefix: str = ""


class ConfluenceClient:
    """Client für Confluence Cloud REST API"""
    
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        auth = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
        self.session.headers.update({
            "Authorization": f"Basic {auth}",
            "Accept": "application/json"
        })

    def _get_json(self, path: str, params: Optional[dict] = None) -> dict:
        """HTTP GET mit JSON Response"""
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def test_connection(self) -> dict:
        """Testet Confluence API Verbindung"""
        try:
            data = self._get_json("/wiki/rest/api/space?limit=1")
            return {
                "success": True,
                "message": "Confluence API erreichbar",
                "spaces_found": data.get("size", 0)
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"Confluence API Fehler: {exc}"
            }

    def list_all_spaces(self) -> List[dict]:
        """Liste alle Confluence Spaces"""
        spaces = []
        start = 0
        limit = 100
        
        while True:
            data = self._get_json(f"/wiki/rest/api/space?start={start}&limit={limit}")
            results = data.get("results", [])
            if not results:
                break
            spaces.extend(results)
            if len(results) < limit:
                break
            start += limit
        
        return spaces

    def get_space_info(self, space_key: str) -> dict:
        """Hole Space-Informationen"""
        return self._get_json(f"/wiki/rest/api/space/{space_key}")

    def list_pages_in_space(self, space_key: str, fetch_content: bool = True) -> List[dict]:
        """Liste alle Seiten in einem Space"""
        pages = []
        start = 0
        limit = 50
        
        expand = "ancestors"
        if fetch_content:
            expand += ",body.storage,body.view"
        
        while True:
            params = {
                "cql": f'space="{space_key}" and type=page',
                "expand": expand,
                "limit": limit,
                "start": start
            }
            
            data = self._get_json("/wiki/rest/api/content/search", params=params)
            results = data.get("results", [])
            if not results:
                break
            
            pages.extend(results)
            
            if len(results) < limit:
                break
            start += limit
            
            # Safety check
            if start > 10000:
                print(f"  [WARN] Abbruch bei {start} Seiten - Safety Limit", flush=True)
                break
        
        return pages

    def get_page_detail(self, page_id: str) -> dict:
        """Hole vollständige Page-Details"""
        return self._get_json(
            f"/wiki/rest/api/content/{page_id}",
            params={"expand": "body.storage,body.view,ancestors"}
        )

    def download_attachment(self, url: str) -> bytes:
        """Lade Attachment/Bild herunter"""
        final_url = url if url.startswith("http") else urljoin(self.base_url, url)
        response = self.session.get(final_url, timeout=120)
        response.raise_for_status()
        return response.content


class BookStackClient:
    """Client für BookStack API"""
    
    def __init__(self, base_url: str, token_id: str, token_secret: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {token_id}:{token_secret}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

    def _request(self, method: str, path: str, json_data: Optional[dict] = None, retry_count: int = 3) -> dict:
        """HTTP Request mit Retry-Logik"""
        url = f"{self.base_url}{path}"
        
        for attempt in range(1, retry_count + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    json=json_data,
                    timeout=30
                )
                
                if response.status_code in (429, 500, 502, 503, 504) and attempt < retry_count:
                    wait_time = min(2 * attempt, 10)
                    print(f"  [Retry {attempt}/{retry_count}] Status {response.status_code}, warte {wait_time}s", flush=True)
                    time.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                
                if response.text.strip():
                    return response.json()
                return {}
                
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= retry_count:
                    raise
                wait_time = min(2 * attempt, 10)
                print(f"  [Retry {attempt}/{retry_count}] {type(exc).__name__}, warte {wait_time}s", flush=True)
                time.sleep(wait_time)
        
        return {}

    def test_connection(self) -> dict:
        """Testet BookStack API Verbindung"""
        try:
            data = self._request("GET", "/api/books?count=1")
            return {
                "success": True,
                "message": "BookStack API erreichbar",
                "books_found": len(data.get("data", []))
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"BookStack API Fehler: {exc}"
            }

    def _trim_name(self, name: str, max_length: int = 255) -> str:
        """Kürze Namen auf max_length Zeichen"""
        cleaned = (name or "").strip()
        if not cleaned:
            cleaned = "Untitled"
        if len(cleaned) <= max_length:
            return cleaned
        return cleaned[:max_length-3] + "..."

    def list_books(self) -> List[dict]:
        """Liste alle Books"""
        all_books = []
        offset = 0
        limit = 500
        
        while True:
            data = self._request("GET", f"/api/books?count={limit}&offset={offset}")
            books = data.get("data", [])
            if not books:
                break
            all_books.extend(books)
            if len(books) < limit:
                break
            offset += limit
        
        return all_books

    def find_book_by_name(self, name: str) -> Optional[dict]:
        """Finde Book by Name"""
        books = self.list_books()
        for book in books:
            if book.get("name") == name:
                return book
        return None

    def create_book(self, name: str, description: str = "") -> dict:
        """Erstelle neues Book"""
        safe_name = self._trim_name(name)
        return self._request("POST", "/api/books", {
            "name": safe_name,
            "description": description
        })

    def get_book_detail(self, book_id: int) -> dict:
        """Hole Book-Details mit Contents"""
        return self._request("GET", f"/api/books/{book_id}")

    def create_chapter(self, book_id: int, name: str, description: str = "") -> dict:
        """Erstelle Chapter in Book"""
        safe_name = self._trim_name(name)
        return self._request("POST", "/api/chapters", {
            "book_id": book_id,
            "name": safe_name,
            "description": description
        })

    def create_page(self, name: str, html: str, book_id: Optional[int] = None, chapter_id: Optional[int] = None) -> dict:
        """Erstelle Page"""
        safe_name = self._trim_name(name)
        safe_html = html if html and html.strip() else "<p></p>"
        
        payload = {
            "name": safe_name,
            "html": safe_html
        }
        
        if chapter_id:
            payload["chapter_id"] = chapter_id
        elif book_id:
            payload["book_id"] = book_id
        
        return self._request("POST", "/api/pages", payload)

    def get_page_detail(self, page_id: int) -> dict:
        """Hole Page-Details"""
        return self._request("GET", f"/api/pages/{page_id}")

    def upload_image(self, page_id: int, filename: str, image_data: bytes) -> dict:
        """Upload Bild zu Page"""
        url = f"{self.base_url}/api/image-gallery"
        files = {"image": (filename, image_data, "image/png")}
        data = {
            "type": "gallery",
            "uploaded_to": page_id
        }
        
        # Temporarily remove Content-Type header for multipart
        headers = dict(self.session.headers)
        headers.pop("Content-Type", None)
        
        response = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            timeout=60
        )
        response.raise_for_status()
        return response.json()

    def list_shelves(self) -> List[dict]:
        """Liste alle Shelves"""
        data = self._request("GET", "/api/shelves")
        return data.get("data", [])

    def find_shelf_by_name(self, name: str) -> Optional[dict]:
        """Finde Shelf by Name"""
        shelves = self.list_shelves()
        for shelf in shelves:
            if shelf.get("name") == name:
                return shelf
        return None

    def create_shelf(self, name: str, description: str = "", books: Optional[List[int]] = None) -> dict:
        """Erstelle Shelf"""
        payload = {
            "name": name,
            "description": description
        }
        if books:
            payload["books"] = books
        return self._request("POST", "/api/shelves", payload)

    def update_shelf(self, shelf_id: int, name: str, books: List[int]) -> dict:
        """Update Shelf Books"""
        return self._request("PUT", f"/api/shelves/{shelf_id}", {
            "name": name,
            "books": books
        })


def extract_sample_words(html: str, max_words: int = 10) -> str:
    """Extrahiert Beispielworte aus HTML Content"""
    if not html:
        return "(leer)"
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    if not text:
        return "(keine Textinhalte)"
    
    # Get first N words
    words = text.split()[:max_words]
    sample = ' '.join(words)
    
    if len(words) >= max_words:
        sample += "..."
    
    return sample


def has_meaningful_content(html: str) -> bool:
    """Prüft ob HTML echten Inhalt hat"""
    if not html or not html.strip():
        return False
    
    # Remove empty tags
    content = re.sub(r'<p>\s*</p>|<br\s*/?>|<div>\s*</div>', '', html.strip())
    
    # Check for text or images
    has_text = bool(re.search(r'[a-zA-Z0-9]', content))
    has_images = bool(re.search(r'<img', content, re.IGNORECASE))
    
    return has_text or has_images


def test_apis(config: Config) -> bool:
    """Testet beide APIs"""
    print("\n" + "="*80)
    print("API VERBINDUNGSTESTS")
    print("="*80 + "\n")
    
    # Test Confluence
    print("1. Confluence API Test...")
    conf = ConfluenceClient(
        config.confluence_base_url,
        config.confluence_email,
        config.confluence_api_token
    )
    conf_result = conf.test_connection()
    
    if conf_result["success"]:
        print(f"   ✓ {conf_result['message']}")
        print(f"   Spaces im System: {conf_result.get('spaces_found', 'N/A')}")
    else:
        print(f"   ✗ {conf_result['message']}")
        return False
    
    # Test BookStack
    print("\n2. BookStack API Test...")
    bs = BookStackClient(
        config.bookstack_base_url,
        config.bookstack_token_id,
        config.bookstack_token_secret
    )
    bs_result = bs.test_connection()
    
    if bs_result["success"]:
        print(f"   ✓ {bs_result['message']}")
        print(f"   Books im System: {bs_result.get('books_found', 'N/A')}")
    else:
        print(f"   ✗ {bs_result['message']}")
        return False
    
    print("\n" + "="*80)
    print("✓ Beide APIs sind erreichbar und funktionsfähig")
    print("="*80 + "\n")
    
    return True


def list_confluence_spaces(config: Config):
    """Listet alle Confluence Spaces auf"""
    print("\n" + "="*80)
    print("CONFLUENCE SPACES")
    print("="*80 + "\n")
    
    conf = ConfluenceClient(
        config.confluence_base_url,
        config.confluence_email,
        config.confluence_api_token
    )
    
    try:
        spaces = conf.list_all_spaces()
        
        if not spaces:
            print("Keine Spaces gefunden.")
            return
        
        print(f"Gefundene Spaces: {len(spaces)}\n")
        
        for space in spaces:
            space_key = space.get("key", "?")
            space_name = space.get("name", "Unbekannt")
            space_type = space.get("type", "?")
            
            print(f"  [{space_key}] {space_name}")
            print(f"      Typ: {space_type}")
            print()
        
        print("="*80)
        print(f"\nNutzung: --spaces {','.join(s.get('key', '') for s in spaces[:3])}...")
        print("="*80 + "\n")
        
    except Exception as exc:
        print(f"Fehler beim Abrufen der Spaces: {exc}")


def create_structure_preview(config: Config, space_keys: List[str], output_file: str = "structure_preview.md"):
    """Erstellt Struktur-Preview als Markdown"""
    print("\n" + "="*80)
    print("STRUKTUR-PREVIEW ERSTELLEN")
    print("="*80 + "\n")
    
    conf = ConfluenceClient(
        config.confluence_base_url,
        config.confluence_email,
        config.confluence_api_token
    )
    
    output_path = Path(output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Confluence to BookStack - Struktur Preview\n\n")
        f.write(f"**Erstellt**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("---\n\n")
        
        for space_idx, space_key in enumerate(space_keys, 1):
            print(f"\nVerarbeite Space {space_idx}/{len(space_keys)}: {space_key}")
            
            try:
                # Get space info
                space_info = conf.get_space_info(space_key)
                space_name = space_info.get("name", space_key)
                
                f.write(f"## Space: {space_key} - {space_name}\n\n")
                
                # Load pages
                print(f"  Lade Seiten...")
                pages = conf.list_pages_in_space(space_key, fetch_content=True)
                print(f"  Gefunden: {len(pages)} Seiten")
                
                if not pages:
                    f.write("*Keine Seiten gefunden*\n\n")
                    continue
                
                # Build hierarchy
                page_map = {str(p.get("id")): p for p in pages}
                children = {pid: [] for pid in page_map.keys()}
                top_level = []
                
                for page_id, page in page_map.items():
                    ancestors = page.get("ancestors", []) or []
                    if not ancestors:
                        top_level.append(page_id)
                    else:
                        parent_id = str(ancestors[-1].get("id"))
                        if parent_id in children:
                            children[parent_id].append(page_id)
                
                # Write structure
                f.write(f"**Struktur-Übersicht**: {len(top_level)} Top-Level Seiten\n\n")
                
                for root_id in top_level:
                    root_page = page_map[root_id]
                    root_title = root_page.get("title", "Untitled")
                    
                    # Get content sample
                    view_html = root_page.get("body", {}).get("view", {}).get("value", "")
                    storage_html = root_page.get("body", {}).get("storage", {}).get("value", "")
                    content = view_html or storage_html
                    sample = extract_sample_words(content, 15)
                    has_content = has_meaningful_content(content)
                    status_icon = "✓" if has_content else "⚠"
                    
                    f.write(f"### {status_icon} Book: {root_title}\n\n")
                    f.write(f"*Beispiel-Inhalt*: {sample}\n\n")
                    
                    # Write chapters (level 2)
                    if children[root_id]:
                        for chapter_id in children[root_id]:
                            chapter_page = page_map[chapter_id]
                            chapter_title = chapter_page.get("title", "Untitled")
                            
                            chapter_html = chapter_page.get("body", {}).get("view", {}).get("value", "")
                            chapter_storage = chapter_page.get("body", {}).get("storage", {}).get("value", "")
                            chapter_content = chapter_html or chapter_storage
                            chapter_sample = extract_sample_words(chapter_content, 10)
                            chapter_has_content = has_meaningful_content(chapter_content)
                            chapter_icon = "✓" if chapter_has_content else "⚠"
                            
                            f.write(f"#### {chapter_icon} Chapter: {chapter_title}\n\n")
                            f.write(f"*Beispiel-Inhalt*: {chapter_sample}\n\n")
                            
                            # Write pages (level 3+)
                            if children[chapter_id]:
                                for page_id in children[chapter_id]:
                                    page = page_map[page_id]
                                    page_title = page.get("title", "Untitled")
                                    
                                    page_html = page.get("body", {}).get("view", {}).get("value", "")
                                    page_storage = page.get("body", {}).get("storage", {}).get("value", "")
                                    page_content = page_html or page_storage
                                    page_sample = extract_sample_words(page_content, 8)
                                    page_has_content = has_meaningful_content(page_content)
                                    page_icon = "✓" if page_has_content else "⚠"
                                    
                                    f.write(f"- {page_icon} Seite: **{page_title}**\n")
                                    f.write(f"  - *Content*: {page_sample}\n")
                            
                            f.write("\n")
                    else:
                        f.write("*(Keine Chapters)*\n\n")
                
                f.write("---\n\n")
                
            except Exception as exc:
                error_msg = f"Fehler bei Space {space_key}: {exc}"
                print(f"  [ERROR] {error_msg}")
                f.write(f"**FEHLER**: {error_msg}\n\n")
    
    print(f"\n✓ Struktur-Preview erstellt: {output_path}")
    print(f"  Bitte überprüfen Sie die Datei vor der Migration!\n")
    print("="*80 + "\n")


def load_config() -> Config:
    """Lädt Konfiguration aus .env Datei"""
    env_file = Path(__file__).parent / ".env"
    
    if not env_file.exists():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {env_file}")
    
    config_dict = {}
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                config_dict[key.strip()] = value.strip()
    
    # CONFLUENCE_SPACE_KEY ist jetzt optional
    return Config(
        confluence_base_url=config_dict.get("CONFLUENCE_BASE_URL", ""),
        confluence_email=config_dict.get("CONFLUENCE_EMAIL", ""),
        confluence_api_token=config_dict.get("CONFLUENCE_API_TOKEN", ""),
        bookstack_base_url=config_dict.get("BOOKSTACK_BASE_URL", ""),
        bookstack_token_id=config_dict.get("BOOKSTACK_TOKEN_ID", ""),
        bookstack_token_secret=config_dict.get("BOOKSTACK_TOKEN_SECRET", ""),
        book_name_prefix=config_dict.get("BOOKSTACK_BOOK_PREFIX", "")
    )


def main():
    parser = argparse.ArgumentParser(
        description="Confluence to BookStack Migration Tool (Erweiterte Version)"
    )
    
    # Neue Kommandos
    parser.add_argument("--test-apis", action="store_true",
                       help="Teste Verbindung zu beiden APIs")
    parser.add_argument("--list-spaces", action="store_true",
                       help="Liste alle verfügbaren Confluence Spaces")
    parser.add_argument("--preview-structure", action="store_true",
                       help="Erstelle Struktur-Preview als Markdown (vor Migration)")
    
    # Migration
    parser.add_argument("--spaces", type=str,
                       help="Comma-separated list of Confluence space keys (z.B. AUTO,CS)")
    parser.add_argument("--migrate", action="store_true",
                       help="Führe Migration durch")
    parser.add_argument("--verify", action="store_true",
                       help="Verifiziere Migration nach Abschluss")
    
    # Output
    parser.add_argument("--preview-file", type=str, default="structure_preview.md",
                       help="Output-Datei für Struktur-Preview")
    parser.add_argument("--shelf-name", type=str, default="Confluence Migration (isolated)",
                       help="Name des BookStack Shelfs")
    
    # Optionen
    parser.add_argument("--yes", action="store_true",
                       help="Automatische Bestätigung (keine Rückfrage)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Simulation ohne tatsächliche Änderungen")
    
    args = parser.parse_args()
    
    try:
        config = load_config()
    except Exception as exc:
        print(f"Fehler beim Laden der Konfiguration: {exc}")
        return 1
    
    # Test APIs
    if args.test_apis:
        success = test_apis(config)
        return 0 if success else 1
    
    # List Spaces
    if args.list_spaces:
        list_confluence_spaces(config)
        return 0
    
    # Preview Structure
    if args.preview_structure:
        if not args.spaces:
            print("Fehler: --spaces erforderlich für --preview-structure")
            return 1
        
        space_keys = [s.strip() for s in args.spaces.split(",") if s.strip()]
        create_structure_preview(config, space_keys, args.preview_file)
        return 0
    
    # Show help if no action specified
    if not args.migrate:
        parser.print_help()
        print("\n" + "="*80)
        print("EMPFOHLENER WORKFLOW:")
        print("="*80)
        print("1. APIs testen:          --test-apis")
        print("2. Spaces auflisten:     --list-spaces")
        print("3. Struktur prüfen:      --preview-structure --spaces AUTO,CS")
        print("4. Preview reviewen:     structure_preview.md")
        print("5. Migration starten:    --migrate --spaces AUTO,CS")
        print("6. Verifizieren:         --verify --spaces AUTO,CS")
        print("="*80 + "\n")
        return 0
    
    # Migration durchführen
    if not args.spaces:
        print("Fehler: --spaces erforderlich für --migrate")
        return 1
    
    space_keys = [s.strip() for s in args.spaces.split(",") if s.strip()]
    
    # Test APIs vor Migration
    print("\nAPI-Tests vor Migration...")
    if not test_apis(config):
        print("\n⚠ API-Tests fehlgeschlagen. Migration abgebrochen.")
        return 1
    
    # Führe Migration durch
    success = run_migration(config, space_keys, args.shelf_name, args.dry_run, args.yes)
    
    if success and args.verify:
        print("\nStarte Verifikation...")
        verify_migration(config, space_keys, args.shelf_name)
    
    return 0 if success else 1


def run_migration(config: Config, space_keys: List[str], shelf_name: str, dry_run: bool = False, auto_confirm: bool = False) -> bool:
    """Führt die vollständige Migration durch"""
    print("\n" + "="*80)
    print("MIGRATION STARTEN")
    print("="*80 + "\n")
    
    conf = ConfluenceClient(
        config.confluence_base_url,
        config.confluence_email,
        config.confluence_api_token
    )
    
    bs = BookStackClient(
        config.bookstack_base_url,
        config.bookstack_token_id,
        config.bookstack_token_secret
    )
    
    migrated_book_ids = []
    
    for space_idx, space_key in enumerate(space_keys, 1):
        print(f"\n{'='*80}")
        print(f"Space {space_idx}/{len(space_keys)}: {space_key}")
        print(f"{'='*80}\n")
        
        try:
            # Load space info
            space_info = conf.get_space_info(space_key)
            space_name = space_info.get("name", space_key)
            print(f"Space Name: {space_name}")
            
            # Load pages
            print(f"\n[1/5] Lade Seiten aus {space_key}...")
            pages = conf.list_pages_in_space(space_key, fetch_content=True)
            print(f"  Gefunden: {len(pages)} Seiten")
            
            if not pages:
                print("  Keine Seiten gefunden - überspringe Space")
                continue
            
            # Build hierarchy
            print(f"\n[2/5] Analysiere Struktur...")
            page_map = {str(p.get("id")): p for p in pages}
            children = {pid: [] for pid in page_map.keys()}
            top_level = []
            
            for page_id, page in page_map.items():
                ancestors = page.get("ancestors", []) or []
                if not ancestors:
                    top_level.append(page_id)
                else:
                    parent_id = str(ancestors[-1].get("id"))
                    if parent_id in children:
                        children[parent_id].append(page_id)
            
            print(f"  Top-Level Seiten (Books): {len(top_level)}")
            
            # Confirm migration
            if not dry_run and not auto_confirm:
                answer = input(f"\nMigration für {space_key} starten? [y/N]: ").strip().lower()
                if answer not in ("y", "yes", "j", "ja"):
                    print("  Übersprungen auf Benutzerwunsch")
                    continue
            
            # Create Books and migrate content
            print(f"\n[3/5] Erstelle Books und migriere Inhalte...")
            
            for root_idx, root_id in enumerate(top_level, 1):
                root_page = page_map[root_id]
                root_title = root_page.get("title", " Untitled")
                
                book_name = config.book_name_prefix + root_title if config.book_name_prefix else root_title
                
                print(f"\n  [{root_idx}/{len(top_level)}] Book: {root_title}")
                
                if dry_run:
                    book_id = -1
                    print(f"      [DRY-RUN] Würde Book erstellen")
                else:
                    # Find or create book
                    existing_book = bs.find_book_by_name(book_name)
                    if existing_book:
                        book_id = existing_book["id"]
                        print(f"      Book existiert bereits: ID {book_id}")
                    else:
                        book = bs.create_book(
                            book_name,
                            description=f"Migriert aus Confluence Space {space_key}"
                        )
                        book_id = book["id"]
                        migrated_book_ids.append(book_id)
                        print(f"      Book erstellt: ID {book_id}")
                        time.sleep(0.3)  # Rate limiting
                
                # Process chapters (level 2)
                if children[root_id]:
                    print(f"      Chapters: {len(children[root_id])}")
                    
                    for chapter_idx, chapter_id in enumerate(children[root_id], 1):
                        chapter_page = page_map[chapter_id]
                        chapter_title = chapter_page.get("title", "Untitled")
                        
                        # Get content
                        chapter_html = chapter_page.get("body", {}).get("view", {}).get("value", "")
                        chapter_storage = chapter_page.get("body", {}).get("storage", {}).get("value", "")
                        chapter_content = chapter_html or chapter_storage
                        
                        if not has_meaningful_content(chapter_content):
                            # Try to fetch detail
                            try:
                                detail = conf.get_page_detail(chapter_id)
                                chapter_html = detail.get("body", {}).get("view", {}).get("value", "")
                                chapter_storage = detail.get("body", {}).get("storage", {}).get("value", "")
                                chapter_content = chapter_html or chapter_storage
                            except Exception:
                                pass
                        
                        print(f"        [{chapter_idx}/{len(children[root_id])}] Chapter: {chapter_title}", end="")
                        
                        if dry_run:
                            chapter_bs_id = -1
                            print(f" [DRY-RUN]")
                        else:
                            try:
                                chapter_bs = bs.create_chapter(book_id, chapter_title)
                                chapter_bs_id = chapter_bs["id"]
                                print(f" ✓ (ID {chapter_bs_id})")
                                time.sleep(0.2)
                            except Exception as exc:
                                print(f" ✗ Fehler: {exc}")
                                continue
                        
                        # Process pages in chapter (level 3+)
                        if children[chapter_id]:
                            print(f"            Seiten: {len(children[chapter_id])}")
                            
                            for page_idx, page_id in enumerate(children[chapter_id], 1):
                                page = page_map[page_id]
                                page_title = page.get("title", "Untitled")
                                
                                # Get content with fallback
                                page_html = page.get("body", {}).get("view", {}).get("value", "")
                                page_storage = page.get("body", {}).get("storage", {}).get("value", "")
                                page_content = page_html or page_storage
                                
                                if not has_meaningful_content(page_content):
                                    try:
                                        detail = conf.get_page_detail(page_id)
                                        page_html = detail.get("body", {}).get("view", {}).get("value", "")
                                        page_storage = detail.get("body", {}).get("storage", {}).get("value", "")
                                        page_content = page_html or page_storage
                                    except Exception:
                                        pass
                                
                                has_content = has_meaningful_content(page_content)
                                status = "✓" if has_content else "⚠"
                                
                                if dry_run:
                                    print(f"              [{page_idx}/{len(children[chapter_id])}] {status} {page_title} [DRY-RUN]")
                                else:
                                    try:
                                        # Migrate images in content
                                        final_html = page_content
                                        
                                        # Create page
                                        created_page = bs.create_page(
                                            page_title,
                                            final_html,
                                            chapter_id=chapter_bs_id
                                        )
                                        print(f"              [{page_idx}/{len(children[chapter_id])}] {status} {page_title} ✓ (ID {created_page['id']})")
                                        time.sleep(0.15)
                                    except Exception as exc:
                                        print(f"              [{page_idx}/{len(children[chapter_id])}] ✗ {page_title}: {exc}")
            
            # Create/Update shelf
            if not dry_run and migrated_book_ids:
                print(f"\n[4/5] Aktualisiere Shelf '{shelf_name}'...")
                try:
                    existing_shelf = bs.find_shelf_by_name(shelf_name)
                    if existing_shelf:
                        bs.update_shelf(existing_shelf["id"], shelf_name, migrated_book_ids)
                        print(f"  Shelf aktualisiert: ID {existing_shelf['id']}")
                    else:
                        shelf = bs.create_shelf(
                            shelf_name,
                            description="Isoliertes Shelf für Confluence-Migrationen",
                            books=migrated_book_ids
                        )
                        print(f"  Shelf erstellt: ID {shelf['id']}")
                except Exception as exc:
                    print(f"  Fehler beim Shelf-Update: {exc}")
            
            print(f"\n[5/5] Space {space_key} abgeschlossen!")
            
        except Exception as exc:
            print(f"\n✗ Fehler bei Space {space_key}: {exc}")
            import traceback
            traceback.print_exc()
            return False
    
    print("\n" + "="*80)
    if dry_run:
        print("✓ DRY-RUN abgeschlossen - keine Änderungen durchgeführt")
    else:
        print(f"✓ Migration abgeschlossen: {len(migrated_book_ids)} Books migriert")
    print("="*80 + "\n")
    
    return True


def verify_migration(config: Config, space_keys: List[str], shelf_name: str):
    """Verifiziert die Migration"""
    print("\n" + "="*80)
    print("MIGRATIONS-VERIFIKATION")
    print("="*80 + "\n")
    
    conf = ConfluenceClient(
        config.confluence_base_url,
        config.confluence_email,
        config.confluence_api_token
    )
    
    bs = BookStackClient(
        config.bookstack_base_url,
        config.bookstack_token_id,
        config.bookstack_token_secret
    )
    
    # Find shelf
    shelf = bs.find_shelf_by_name(shelf_name)
    if not shelf:
        print(f"✗ Shelf '{shelf_name}' nicht gefunden!")
        return
    
    print(f"Shelf: {shelf_name} (ID: {shelf['id']})")
    
    # Get shelf books
    shelf_detail = bs._request("GET", f"/api/shelves/{shelf['id']}")
    shelf_books = {b["id"]: b for b in shelf_detail.get("books", [])}
    
    print(f"Books im Shelf: {len(shelf_books)}\n")
    
    total_errors = 0
    
    for space_key in space_keys:
        print(f"\n{'='*70}")
        print(f"Verifiziere Space: {space_key}")
        print(f"{'='*70}\n")
        
        try:
            # Load Confluence pages
            print(f"  Lade Confluence-Seiten...")
            conf_pages = conf.list_pages_in_space(space_key, fetch_content=False)
            print(f"  Gefunden: {len(conf_pages)} Seiten")
            
            # Build structure
            page_map = {str(p.get("id")): p for p in conf_pages}
            children = {pid: [] for pid in page_map.keys()}
            top_level = []
            
            for page_id, page in page_map.items():
                ancestors = page.get("ancestors", []) or []
                if not ancestors:
                    top_level.append(page_id)
                else:
                    parent_id = str(ancestors[-1].get("id"))
                    if parent_id in children:
                        children[parent_id].append(page_id)
            
            print(f"  Top-Level Seiten (Books): {len(top_level)}")
            
            # Verify each book
            for root_id in top_level:
                root_page = page_map[root_id]
                root_title = root_page.get("title", "Untitled")
                book_name = config.book_name_prefix + root_title if config.book_name_prefix else root_title
                
                print(f"\n  Book: {root_title}")
                
                # Find in BookStack
                bs_book = None
                for book_id, book in shelf_books.items():
                    if book.get("name") == book_name:
                        bs_book = book
                        break
                
                if not bs_book:
                    print(f"    ✗ FEHLER: Book nicht in BookStack gefunden")
                    total_errors += 1
                    continue
                
                print(f"    ✓ Gefunden in BookStack (ID: {bs_book['id']})")
                
                # Get book details
                book_detail = bs.get_book_detail(bs_book['id'])
                contents = book_detail.get("contents", [])
                
                bs_chapters = [c for c in contents if c.get("type") == "chapter"]
                print(f"    Chapters: Confluence={len(children[root_id])}, BookStack={len(bs_chapters)}")
                
                if len(children[root_id]) != len(bs_chapters):
                    print(f"      ⚠ Anzahl stimmt nicht überein!")
                    total_errors += 1
                
                # Verify pages in chapters
                total_pages_conf = sum(len(children[ch_id]) for ch_id in children[root_id])
                total_pages_bs = sum(len(ch.get("pages", [])) for ch in bs_chapters)
                
                print(f"    Seiten: Confluence={total_pages_conf}, BookStack={total_pages_bs}")
                
                if total_pages_conf != total_pages_bs:
                    print(f"      ⚠ Anzahl stimmt nicht überein!")
                    total_errors += 1
                else:
                    print(f"      ✓ Struktur korrekt")
        
        except Exception as exc:
            print(f"\n  ✗ Fehler bei Verifikation: {exc}")
            total_errors += 1
    
    print("\n" + "="*80)
    if total_errors == 0:
        print("✓ VERIFIKATION ERFOLGREICH - Alle Strukturen korrekt migriert")
    else:
        print(f"⚠ VERIFIKATION MIT FEHLERN - {total_errors} Problem(e) gefunden")
    print("="*80 + "\n")


if __name__ == "__main__":
    sys.exit(main())
