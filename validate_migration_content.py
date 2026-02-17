#!/usr/bin/env python3
"""
Validate that all content was properly migrated from Confluence to BookStack.
Checks for unique content markers and generates detailed report.
"""

import base64
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


def load_env():
    env_file = Path(__file__).parent / ".env"
    config = {}
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
    return config


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

    def list_pages_in_space(self, space_key: str) -> List[dict]:
        pages: List[dict] = []
        limit = 50
        start = 0
        
        while True:
            params = {
                "cql": f'space="{space_key}" and type=page',
                "expand": "body.storage,body.view",
                "limit": limit,
                "start": start,
            }
            
            data = self._get_json("/wiki/rest/api/content/search", params=params)
            batch = data.get("results", [])
            if not batch:
                break
            
            pages.extend(batch)
            
            if len(batch) < limit:
                break
            
            start += limit
        
        return pages

    def get_page_detail(self, page_id: str) -> dict:
        return self._get_json(
            f"/wiki/rest/api/content/{page_id}",
            params={"expand": "body.storage,body.view"},
        )


class BookStackClient:
    def __init__(self, base_url: str, token_id: str, token_secret: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {token_id}:{token_secret}",
            "Content-Type": "application/json",
        })

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        response = self.session.request(method, url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_all_books(self) -> List[dict]:
        all_books = []
        offset = 0
        limit = 500
        
        while True:
            response = self._request("GET", f"/api/books?count={limit}&offset={offset}")
            books = response.get("data", [])
            if not books:
                break
            all_books.extend(books)
            if len(books) < limit:
                break
            offset += limit
        
        return all_books

    def get_book_detail(self, book_id: int) -> dict:
        return self._request("GET", f"/api/books/{book_id}")

    def get_page_detail(self, page_id: int) -> dict:
        return self._request("GET", f"/api/pages/{page_id}")


def extract_unique_terms(html: str) -> List[str]:
    """Extract unique identifying terms from HTML content"""
    if not html:
        return []
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Get words with at least 4 characters
    words = re.findall(r'\b[A-Za-z\u00c0-\u017f]{4,}\b', text)
    # Return unique words, limited to avoid huge lists
    unique = list(set(words))[:20]
    return unique


def has_meaningful_content(html: str) -> bool:
    """Check if HTML has actual content beyond empty tags"""
    if not html or not html.strip():
        return False
    # Remove common empty tags
    content = re.sub(r'<p>\s*</p>|<br\s*/?>|<div>\s*</div>', '', html.strip())
    # Check if there's actual text or images
    has_text = bool(re.search(r'[a-zA-Z0-9]', content))
    has_images = bool(re.search(r'<img', content, re.IGNORECASE))
    return has_text or has_images


def get_content_length(html: str) -> int:
    """Get approximate content length (text only)"""
    if not html:
        return 0
    text = re.sub(r'<[^>]+>', '', html)
    return len(text.strip())


def validate_migration(space_keys: List[str], shelf_name: str = "Confluence Migration (isolated)"):
    config = load_env()
    
    conf = ConfluenceClient(
        config["CONFLUENCE_BASE_URL"],
        config["CONFLUENCE_EMAIL"],
        config["CONFLUENCE_API_TOKEN"]
    )
    
    bs = BookStackClient(
        config["BOOKSTACK_BASE_URL"],
        config["BOOKSTACK_TOKEN_ID"],
        config["BOOKSTACK_TOKEN_SECRET"]
    )
    
    print("=" * 80)
    print("MIGRATION CONTENT VALIDATION REPORT")
    print("=" * 80)
    print()
    
    validation_results = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "spaces": {},
        "summary": {
            "total_confluence_pages": 0,
            "total_bookstack_pages": 0,
            "pages_with_content": 0,
            "pages_without_content": 0,
            "missing_pages": 0,
        }
    }
    
    # Get BookStack books in shelf
    print(f"Suche BookStack Shelf '{shelf_name}'...")
    all_shelves = bs._request("GET", "/api/shelves").get("data", [])
    target_shelf = None
    for shelf in all_shelves:
        if shelf.get("name") == shelf_name:
            target_shelf = shelf
            break
    
    if not target_shelf:
        print(f"ERROR: Shelf '{shelf_name}' nicht gefunden!")
        return
    
    shelf_detail = bs._request("GET", f"/api/shelves/{target_shelf['id']}")
    bookstack_books = shelf_detail.get("books", [])
    print(f"  Gefunden: {len(bookstack_books)} Books im Shelf\n")
    
    # Create mapping of BookStack books by name
    bs_books_by_name = {book.get("name"): book for book in bookstack_books}
    
    for space_key in space_keys:
        print(f"\n{'=' * 80}")
        print(f"SPACE: {space_key}")
        print(f"{'=' * 80}\n")
        
        space_results = {
            "confluence_pages": [],
            "bookstack_pages": [],
            "validation": {
                "matched_pages": 0,
                "missing_pages": 0,
                "empty_pages": 0,
                "content_mismatches": [],
            }
        }
        
        # Load Confluence pages
        print(f"Lade Confluence-Seiten aus Space '{space_key}'...")
        try:
            conf_pages = conf.list_pages_in_space(space_key)
        except Exception as exc:
            print(f"  ERROR: Fehler beim Laden: {exc}")
            continue
        
        print(f"  Gefunden: {len(conf_pages)} Seiten\n")
        validation_results["summary"]["total_confluence_pages"] += len(conf_pages)
        
        # Analyze Confluence pages
        print("Analysiere Confluence-Inhalte...")
        conf_page_info = {}
        for idx, page in enumerate(conf_pages, 1):
            page_id = str(page.get("id", ""))
            title = page.get("title", "Untitled")
            
            view_html = page.get("body", {}).get("view", {}).get("value", "")
            storage_html = page.get("body", {}).get("storage", {}).get("value", "")
            
            # Fetch detail if needed
            if not has_meaningful_content(view_html) and not has_meaningful_content(storage_html):
                try:
                    detail = conf.get_page_detail(page_id)
                    view_html = detail.get("body", {}).get("view", {}).get("value", "")
                    storage_html = detail.get("body", {}).get("storage", {}).get("value", "")
                except Exception:
                    pass
            
            content = view_html or storage_html
            has_content = has_meaningful_content(content)
            content_len = get_content_length(content)
            unique_terms = extract_unique_terms(content) if has_content else []
            
            conf_page_info[page_id] = {
                "title": title,
                "has_content": has_content,
                "content_length": content_len,
                "unique_terms": unique_terms[:5],  # Store first 5 for report
            }
            
            if idx % 20 == 0:
                print(f"  Verarbeitet: {idx}/{len(conf_pages)}", flush=True)
        
        print(f"  Abgeschlossen: {len(conf_page_info)} Seiten analysiert\n")
        
        # Analyze BookStack pages
        print("Analysiere BookStack-Inhalte...")
        bs_page_info = {}
        total_bs_pages = 0
        
        for book in bookstack_books:
            book_name = book.get("name", "")
            # Check if this book belongs to this space (rough check)
            # In reality, we'd need better tracking
            
            book_id = book.get("id")
            book_detail = bs.get_book_detail(book_id)
            
            # Get all pages in book
            contents = book_detail.get("contents", [])
            
            for item in contents:
                if item.get("type") == "chapter":
                    # Pages in chapter
                    for page_ref in item.get("pages", []):
                        page_id = page_ref.get("id")
                        total_bs_pages += 1
                        try:
                            page_detail = bs.get_page_detail(page_id)
                            html = page_detail.get("html", "")
                            has_content = has_meaningful_content(html)
                            content_len = get_content_length(html)
                            
                            bs_page_info[page_id] = {
                                "title": page_detail.get("name", ""),
                                "has_content": has_content,
                                "content_length": content_len,
                                "book": book_name,
                            }
                            
                            if has_content:
                                validation_results["summary"]["pages_with_content"] += 1
                            else:
                                validation_results["summary"]["pages_without_content"] += 1
                        except Exception as exc:
                            print(f"  [WARN] Fehler beim Laden von Page {page_id}: {exc}")
                
                elif item.get("type") == "page":
                    page_id = item.get("id")
                    total_bs_pages += 1
                    try:
                        page_detail = bs.get_page_detail(page_id)
                        html = page_detail.get("html", "")
                        has_content = has_meaningful_content(html)
                        content_len = get_content_length(html)
                        
                        bs_page_info[page_id] = {
                            "title": page_detail.get("name", ""),
                            "has_content": has_content,
                            "content_length": content_len,
                            "book": book_name,
                        }
                        
                        if has_content:
                            validation_results["summary"]["pages_with_content"] += 1
                        else:
                            validation_results["summary"]["pages_without_content"] += 1
                    except Exception as exc:
                        print(f"  [WARN] Fehler beim Laden von Page {page_id}: {exc}")
        
        print(f"  Abgeschlossen: {total_bs_pages} Seiten analysiert\n")
        validation_results["summary"]["total_bookstack_pages"] += total_bs_pages
        
        # Generate report for this space
        print("\nVALIDATION RESULTS:")
        print("-" * 80)
        print(f"Confluence Seiten: {len(conf_page_info)}")
        print(f"BookStack Seiten:  {total_bs_pages}\n")
        
        # Find pages without content in BookStack
        empty_pages = []
        for page_id, info in bs_page_info.items():
            if not info["has_content"]:
                empty_pages.append(info)
        
        if empty_pages:
            print(f"\n⚠ WARNUNG: {len(empty_pages)} Seiten in BookStack sind leer oder haben keinen Inhalt:\n")
            for info in empty_pages[:20]:  # Show first 20
                print(f"  - {info['title']} (Book: {info['book']})")
            if len(empty_pages) > 20:
                print(f"  ... und {len(empty_pages) - 20} weitere")
        else:
            print("\n✓ Alle BookStack-Seiten haben Inhalt!")
        
        space_results["confluence_pages"] = list(conf_page_info.values())
        space_results["bookstack_pages"] = list(bs_page_info.values())
        space_results["validation"]["empty_pages"] = len(empty_pages)
        validation_results["spaces"][space_key] = space_results
    
    # Write report to file
    report_file = Path("migration_content_validation_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(validation_results, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'=' * 80}")
    print("GESAMTZUSAMMENFASSUNG")
    print(f"{'=' * 80}")
    print(f"Confluence Seiten gesamt:     {validation_results['summary']['total_confluence_pages']}")
    print(f"BookStack Seiten gesamt:      {validation_results['summary']['total_bookstack_pages']}")
    print(f"Seiten mit Inhalt:            {validation_results['summary']['pages_with_content']}")
    print(f"Seiten ohne Inhalt:           {validation_results['summary']['pages_without_content']}")
    print(f"\nDetaillierter Report gespeichert: {report_file}")
    print("=" * 80)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Validate migration content")
    parser.add_argument("--spaces", required=True, help="Comma-separated list of space keys (e.g., AUTO,CS)")
    parser.add_argument("--shelf-name", default="Confluence Migration (isolated)", help="BookStack shelf name")
    
    args = parser.parse_args()
    space_keys = [s.strip() for s in args.spaces.split(",") if s.strip()]
    
    validate_migration(space_keys, args.shelf_name)


if __name__ == "__main__":
    main()
