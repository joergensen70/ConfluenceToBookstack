import os
from pathlib import Path

import requests

from confluence_to_bookstack_migration import load_config_from_env


PAGE_ID = "208633859"


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_dotenv(Path(".env"))
    cfg = load_config_from_env()

    response = requests.get(
        f"{cfg.confluence_base_url.rstrip('/')}/wiki/rest/api/content/{PAGE_ID}",
        auth=(cfg.confluence_email, cfg.confluence_api_token),
        timeout=30,
    )

    print(f"CONFLUENCE_STATUS={response.status_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
