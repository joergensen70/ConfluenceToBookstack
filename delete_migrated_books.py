#!/usr/bin/env python3
"""Delete all books from the Confluence Migration shelf"""

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
    
    # Find the shelf
    print("Suche Shelf 'Confluence Migration (isolated)'...", flush=True)
    response = requests.get(f"{base_url}/api/shelves", headers=headers, timeout=30)
    response.raise_for_status()
    shelves = response.json().get("data", [])
    
    shelf_id = None
    for shelf in shelves:
        if shelf.get("name") == "Confluence Migration (isolated)":
            shelf_id = shelf.get("id")
            break
    
    if not shelf_id:
        print("Shelf nicht gefunden - keine Books zu löschen.")
        return
    
    print(f"Shelf gefunden: ID {shelf_id}", flush=True)
    
    # Get all books in the shelf
    response = requests.get(f"{base_url}/api/shelves/{shelf_id}", headers=headers, timeout=30)
    response.raise_for_status()
    shelf_data = response.json()
    books = shelf_data.get("books", [])
    
    if not books:
        print("Keine Books im Shelf gefunden.")
        return
    
    print(f"\nLösche {len(books)} Books aus dem Shelf...", flush=True)
    
    deleted_count = 0
    for book in books:
        book_id = book.get("id")
        book_name = book.get("name", "Unbekannt")
        
        try:
            response = requests.delete(f"{base_url}/api/books/{book_id}", headers=headers, timeout=30)
            response.raise_for_status()
            print(f"✓ Gelöscht: {book_name} (ID: {book_id})", flush=True)
            deleted_count += 1
        except Exception as exc:
            print(f"✗ Fehler beim Löschen '{book_name}': {exc}", flush=True)
    
    print(f"\n{deleted_count} von {len(books)} Books erfolgreich gelöscht.", flush=True)


if __name__ == "__main__":
    main()
