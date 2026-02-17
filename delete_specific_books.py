#!/usr/bin/env python3
"""Delete specific books by ID"""

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
    
    # Delete books 68 and 69
    book_ids = [68, 69]
    
    for book_id in book_ids:
        try:
            # Get book name first
            response = requests.get(f"{base_url}/api/books/{book_id}", headers=headers, timeout=30)
            if response.status_code == 404:
                print(f"Book {book_id} not found - already deleted?")
                continue
            response.raise_for_status()
            book_data = response.json()
            book_name = book_data.get("name", "Unknown")
            
            # Delete it
            response = requests.delete(f"{base_url}/api/books/{book_id}", headers=headers, timeout=30)
            response.raise_for_status()
            print(f"✓ Deleted: {book_name} (ID: {book_id})")
        except Exception as exc:
            print(f"✗ Error deleting book {book_id}: {exc}")


if __name__ == "__main__":
    main()
