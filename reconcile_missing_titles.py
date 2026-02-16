import difflib
import json
import os
from pathlib import Path

from confluence_to_bookstack_migration import BookStackClient, load_config_from_env

REPORT = Path("cn_content_diff_cleanup_report.json")


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def simplified(text: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    report = json.loads(REPORT.read_text(encoding='utf-8'))
    target_book_id = int(report["target_book"]["id"])
    missing = report.get("missing_expected", [])

    pages = bs._request("GET", "/api/pages?count=500").get("data", [])
    target_pages = [p for p in pages if int(p.get("book_id", -1)) == target_book_id]

    used = set()
    renamed = []

    for miss in missing:
        miss_s = simplified(miss)
        best = None
        best_ratio = 0.0

        for p in target_pages:
            pid = int(p["id"])
            if pid in used:
                continue
            name = p.get("name", "")
            ratio = difflib.SequenceMatcher(None, miss_s, simplified(name)).ratio()
            # prefix bonus for technical long titles
            if miss_s[:35] and simplified(name).startswith(miss_s[:35]):
                ratio += 0.12
            if ratio > best_ratio:
                best_ratio = ratio
                best = p

        if best is None or best_ratio < 0.72:
            print(f"NO_FUZZY_MATCH={miss}")
            continue

        pid = int(best["id"])
        detail = bs._request("GET", f"/api/pages/{pid}")
        payload = {
            "name": miss,
            "html": detail.get("raw_html") or detail.get("html") or "<p></p>",
        }
        if detail.get("chapter_id"):
            payload["chapter_id"] = detail.get("chapter_id")
        else:
            payload["book_id"] = detail.get("book_id")

        bs._request("PUT", f"/api/pages/{pid}", payload)
        used.add(pid)
        renamed.append({"page_id": pid, "old_name": best.get("name", ""), "new_name": miss, "ratio": round(best_ratio, 3)})
        print(f"RENAMED={pid}::{best.get('name','')}::{miss}::{round(best_ratio,3)}")

    print(f"RENAMED_COUNT={len(renamed)}")
    Path("reconcile_missing_titles_report.json").write_text(json.dumps({"renamed": renamed}, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
