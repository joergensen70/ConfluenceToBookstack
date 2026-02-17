#!/usr/bin/env python3
"""Test BookStack API responsiveness"""

import os
import requests
import time
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
    
    print("Testing BookStack API...\n")
    
    # Test 1: List books
    print("1. Listing books (count=500)...")
    start = time.time()
    try:
        response = requests.get(f"{base_url}/api/books?count=500", headers=headers, timeout=30)
        elapsed = time.time() - start
        print(f"  ✓ Response time: {elapsed:.2f}s")
        print(f"  Status: {response.status_code}")
        if response.ok:
            data = response.json()
            print(f"  Books found: {len(data.get('data', []))}")
    except Exception as exc:
        elapsed = time.time() - start
        print(f"  ✗ Failed after {elapsed:.2f}s: {exc}")
    
    # Test 2: List shelves
    print("\n2. Listing shelves...")
    start = time.time()
    try:
        response = requests.get(f"{base_url}/api/shelves", headers=headers, timeout=30)
        elapsed = time.time() - start
        print(f"  ✓ Response time: {elapsed:.2f}s")
        print(f"  Status: {response.status_code}")
        if response.ok:
            data = response.json()
            print(f"  Shelves found: {len(data.get('data', []))}")
    except Exception as exc:
        elapsed = time.time() - start
        print(f"  ✗ Failed after {elapsed:.2f}s: {exc}")
    
    # Test 3: Create and delete a test book
    print("\n3. Creating test book...")
    start = time.time()
    try:
        payload = {"name": "API Test Book (DELETE ME)", "description": "Testing API"}
        response = requests.post(f"{base_url}/api/books", headers=headers, json=payload, timeout=30)
        elapsed = time.time() - start
        print(f"  ✓ Response time: {elapsed:.2f}s")
        print(f"  Status: {response.status_code}")
        
        if response.ok:
            book_id = response.json().get("id")
            print(f"  Book created: ID {book_id}")
            
            # Delete it
            print("\n4. Deleting test book...")
            start = time.time()
            response = requests.delete(f"{base_url}/api/books/{book_id}", headers=headers, timeout=30)
            elapsed = time.time() - start
            print(f"  ✓ Response time: {elapsed:.2f}s")
            print(f"  Status: {response.status_code}")
    except Exception as exc:
        elapsed = time.time() - start
        print(f"  ✗ Failed after {elapsed:.2f}s: {exc}")
    
    print("\nAPI test complete.")


if __name__ == "__main__":
    main()
