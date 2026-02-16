import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from confluence_to_bookstack_migration import BookStackClient, ConfluenceClient, load_config_from_env

REPORT = Path("cn_content_diff_cleanup_report.json")


def load_dotenv(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " und ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_target_book(bs: BookStackClient) -> dict:
    books = bs._request("GET", "/api/books?count=500").get("data", [])
    for book in books:
        name_n = norm(book.get("name", ""))
        slug = (book.get("slug") or "").lower()
        if ("confluence" in name_n and "computer" in name_n and "netzwerk" in name_n) or (
            "confluence-computer-netzwerk" in slug
        ):
            return book
    raise RuntimeError("CN target book not found")


def build_expected_titles(conf: ConfluenceClient, space_key: str) -> List[str]:
    pages = conf.list_pages_in_space(space_key)
    page_map = {p["id"]: p for p in pages}
    children: Dict[str, List[str]] = {p["id"]: [] for p in pages}
    top_level: List[str] = []

    for page in pages:
        ancestors = page.get("ancestors", []) or []
        parent_id = None
        for anc in reversed(ancestors):
            aid = anc.get("id")
            if aid in page_map:
                parent_id = aid
                break
        if parent_id:
            children[parent_id].append(page["id"])
        else:
            top_level.append(page["id"])

    expected: List[str] = []

    for root_id in top_level:
        root_page = page_map[root_id]
        has_children = len(children[root_id]) > 0
        root_title = root_page.get("title", "Untitled")
        expected.append(root_title)

        if has_children:
            queue = list(children[root_id])
            while queue:
                node_id = queue.pop(0)
                node = page_map[node_id]

                anc_titles: List[str] = []
                for anc in node.get("ancestors", []) or []:
                    aid = anc.get("id")
                    if aid in page_map:
                        anc_titles.append(page_map[aid].get("title", ""))
                anc_titles.append(node.get("title", "Untitled"))

                trail = " / ".join(anc_titles[1:]) if len(anc_titles) > 1 else anc_titles[0]
                expected.append(trail)
                queue[0:0] = children[node_id]

    return expected


def score_page(bs: BookStackClient, page_id: int) -> tuple[int, int, int]:
    detail = bs._request("GET", f"/api/pages/{page_id}")
    html = detail.get("raw_html") or detail.get("html") or ""
    img_count = len(re.findall(r"<img\\b", html, flags=re.IGNORECASE))
    return (img_count, len(html), page_id)


def main() -> int:
    load_dotenv(Path('.env'))
    cfg = load_config_from_env()

    conf = ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    bs = BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)

    target_book = find_target_book(bs)
    target_book_id = int(target_book["id"])

    expected_titles = build_expected_titles(conf, cfg.confluence_space_key)
    expected_norm_map = {norm(t): t for t in expected_titles}

    pages = bs._request("GET", "/api/pages?count=500").get("data", [])
    target_pages = [p for p in pages if int(p.get("book_id", -1)) == target_book_id]

    by_norm: Dict[str, List[dict]] = defaultdict(list)
    for page in target_pages:
        by_norm[norm(page.get("name", ""))].append(page)

    missing_expected = []
    keep_ids = set()
    duplicate_deletions = []

    for key, expected_title in expected_norm_map.items():
        group = by_norm.get(key, [])
        if not group:
            missing_expected.append(expected_title)
            continue
        if len(group) == 1:
            keep_ids.add(int(group[0]["id"]))
            continue

        scored = []
        for p in group:
            pid = int(p["id"])
            try:
                scored.append((score_page(bs, pid), p))
            except Exception:
                scored.append(((0, 0, pid), p))
        scored.sort(reverse=True)

        keep = scored[0][1]
        keep_ids.add(int(keep["id"]))
        for _, loser in scored[1:]:
            duplicate_deletions.append(
                {
                    "page_id": int(loser["id"]),
                    "name": loser.get("name", ""),
                    "reason": f"duplicate_of_expected:{expected_title}",
                    "kept_page_id": int(keep["id"]),
                }
            )

    extra_deletions = []
    for key, group in by_norm.items():
        if key in expected_norm_map:
            continue
        for p in group:
            extra_deletions.append(
                {
                    "page_id": int(p["id"]),
                    "name": p.get("name", ""),
                    "reason": "not_in_confluence_expected_titles",
                }
            )

    deleted = []
    errors = []

    to_delete = duplicate_deletions + extra_deletions
    # stable deterministic deletion order
    to_delete.sort(key=lambda x: x["page_id"])

    for item in to_delete:
        pid = int(item["page_id"])
        if pid in keep_ids:
            continue
        try:
            bs._request("DELETE", f"/api/pages/{pid}")
            deleted.append(item)
        except Exception as exc:
            err = dict(item)
            err["error"] = str(exc)
            errors.append(err)

    pages_after = bs._request("GET", "/api/pages?count=500").get("data", [])
    target_after = [p for p in pages_after if int(p.get("book_id", -1)) == target_book_id]

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_book": {"id": target_book_id, "name": target_book.get("name"), "slug": target_book.get("slug")},
        "confluence_expected_count": len(expected_titles),
        "book_pages_before": len(target_pages),
        "book_pages_after": len(target_after),
        "missing_expected_count": len(missing_expected),
        "missing_expected": missing_expected,
        "duplicate_candidates": duplicate_deletions,
        "extra_candidates": extra_deletions,
        "deleted_count": len(deleted),
        "deleted": deleted,
        "error_count": len(errors),
        "errors": errors,
    }

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"TARGET_BOOK_ID={target_book_id}")
    print(f"EXPECTED={len(expected_titles)}")
    print(f"BEFORE={len(target_pages)}")
    print(f"DELETED={len(deleted)}")
    print(f"AFTER={len(target_after)}")
    print(f"MISSING_EXPECTED={len(missing_expected)}")
    print(f"ERRORS={len(errors)}")
    print(f"REPORT={REPORT}")
    return 0 if len(errors) == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
