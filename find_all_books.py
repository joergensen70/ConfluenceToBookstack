#!/usr/bin/env python3
"""Find all books in BookStack, regardless of shelf"""

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
    
    # Get ALL books
    print("Fetching all books...")
    all_books = []
    offset = 0
    limit = 100
    
    while True:
        response = requests.get(f"{base_url}/api/books?count={limit}&offset={offset}", headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        books = data.get("data", [])
        if not books:
            break
        all_books.extend(books)
        if len(books) < limit:
            break
        offset += limit
    
    print(f"\nTotal books in BookStack: {len(all_books)}\n")
    
    # Look for our migration books
    migration_books = []
    for book in all_books:
        name = book.get("name", "")
        if any(keyword in name for keyword in ["Passat", "Umbauten", "Cliff", "Volkszähler", "Internet"]):
            migration_books.append(book)
            
    if migration_books:
        print(f"Found {len(migration_books)} potential migration books:\n")
        for book in migration_books:
            book_id = book.get("id")
            book_name = book.get("name")
            
            # Get book details
            response = requests.get(f"{base_url}/api/books/{book_id}", headers=headers, timeout=30)
            response.raise_for_status()
            book_detail = response.json()
            
            contents = book_detail.get("contents", [])
            chapters = [c for c in contents if c.get("type") == "chapter"]
            pages = [c for c in contents if c.get("type") == "page"]
            
            total_chapter_pages = sum(len(c.get("pages", [])) for c in chapters)
            
            print(f"Book: {book_name} (ID: {book_id})")
            print(f"  Chapters: {len(chapters)}, Pages in chapters: {total_chapter_pages}, Direct pages: {len(pages)}")
            print()
    else:
        print("No migration books found.")


if __name__ == "__main__":
    main()
