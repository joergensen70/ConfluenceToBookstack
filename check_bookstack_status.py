#!/usr/bin/env python3
"""Quick check of what exists in BookStack"""

import os
import requests
from pathlib import Path


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


def main():
    config = load_env()
    base_url = config["BOOKSTACK_BASE_URL"].rstrip("/")
    token_id = config["BOOKSTACK_TOKEN_ID"]
    token_secret = config["BOOKSTACK_TOKEN_SECRET"]
    
    headers = {
        "Authorization": f"Token {token_id}:{token_secret}",
        "Content-Type": "application/json",
    }
    
    # Get shelf
    print("Checking Shelf...")
    response = requests.get(f"{base_url}/api/shelves", headers=headers, timeout=30)
    response.raise_for_status()
    shelves = response.json().get("data", [])
    
    for shelf in shelves:
        if shelf.get("name") == "Confluence Migration (isolated)":
            shelf_id = shelf.get("id")
            response = requests.get(f"{base_url}/api/shelves/{shelf_id}", headers=headers, timeout=30)
            response.raise_for_status()
            shelf_data = response.json()
            books = shelf_data.get("books", [])
            
            print(f"\nShelf: {shelf.get('name')} (ID: {shelf_id})")
            print(f"Books: {len(books)}\n")
            
            for book in books:
                book_id = book.get("id")
                book_name = book.get("name")
                
                # Get book details
                response = requests.get(f"{base_url}/api/books/{book_id}", headers=headers, timeout=30)
                response.raise_for_status()
                book_detail = response.json()
                
                contents = book_detail.get("contents", [])
                chapters = [c for c in contents if c.get("type") == "chapter"]
                pages = [c for c in contents if c.get("type") == "page"]
                
                print(f"Book: {book_name} (ID: {book_id})")
                print(f"  Chapters: {len(chapters)}")
                print(f"  Direct Pages: {len(pages)}")
                
                # Count pages in chapters
                total_chapter_pages = 0
                for chapter in chapters:
                    chapter_pages = len(chapter.get("pages", []))
                    total_chapter_pages += chapter_pages
                    print(f"    - {chapter.get('name')}: {chapter_pages} pages")
                
                print(f"  Total Pages in Chapters: {total_chapter_pages}")
                print()


if __name__ == "__main__":
    main()
