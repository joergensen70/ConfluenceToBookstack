import os
import re
import unicodedata
from pathlib import Path

import requests

TARGETS = [
    "Web Cam",
    "Anleitungsartikel",
    "RS485/Modbus Stromzähler",
    "Outlook 365 winmail.dat",
    "Moved to bookstack",
    "Optional Hostname",
]


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def main() -> int:
    load_dotenv(Path(".env"))
    base = os.environ["BOOKSTACK_BASE_URL"].rstrip("/")
    token = f"Token {os.environ['BOOKSTACK_TOKEN_ID']}:{os.environ['BOOKSTACK_TOKEN_SECRET']}"

    response = requests.get(
        f"{base}/api/pages",
        params={"count": 500},
        headers={"Authorization": token, "Accept": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    all_pages = response.json().get("data", [])

    for target in TARGETS:
        token_norm = norm(target)
        matches = [item for item in all_pages if token_norm in norm(item.get("name", ""))]
        print(f"{target}::{len(matches)}")
        for item in matches[:5]:
            print(f"  - {item.get('name','')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
