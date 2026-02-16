import base64
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

ROOT = Path(__file__).resolve().parent
SPACES = ["cs", "auto"]
OUTPUT_FILE = ROOT / "confluence_structure_cs_auto.md"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class ConfluenceSimpleClient:
    def __init__(self, base_url: str, email: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        auth = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        self.session.headers.update({"Authorization": f"Basic {auth}", "Accept": "application/json"})

    def _get_json(self, path: str, params: dict | None = None) -> dict:
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=60)
        response.raise_for_status()
        return response.json()

    def resolve_space_key(self, space_key: str) -> str:
        candidates = [space_key, space_key.upper(), space_key.lower()]
        seen: set[str] = set()
        for key in candidates:
            if key in seen:
                continue
            seen.add(key)
            try:
                self._get_json(f"/wiki/rest/api/space/{key}")
                return key
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 404:
                    continue
                raise
        raise RuntimeError(f"Confluence-Space nicht gefunden: {space_key}")

    def get_space_name(self, space_key: str) -> str:
        data = self._get_json(f"/wiki/rest/api/space/{space_key}")
        return data.get("name") or space_key

    def list_spaces(self) -> list[dict]:
        spaces: list[dict] = []
        start = 0
        limit = 200

        for _ in range(50):
            data = self._get_json("/wiki/rest/api/space", {"limit": limit, "start": start})
            batch = data.get("results", [])
            if not batch:
                break
            spaces.extend(batch)
            if len(batch) < limit:
                break
            start += len(batch)

        return spaces

    def list_pages_in_space(self, space_key: str) -> list[dict]:
        pages: list[dict] = []
        limit = 50
        seen_ids: set[str] = set()
        cursor: str | None = None
        seen_cursors: set[str] = set()

        for _ in range(2000):
            params = {
                "cql": f'space="{space_key}" and type=page',
                "expand": "ancestors",
                "limit": limit,
            }
            if cursor:
                params["cursor"] = cursor
            else:
                params["start"] = 0

            data = self._get_json("/wiki/rest/api/content/search", params=params)
            batch = data.get("results", [])
            if not batch:
                break

            new_items = 0
            for item in batch:
                pid = str(item.get("id", ""))
                if pid and pid in seen_ids:
                    continue
                if pid:
                    seen_ids.add(pid)
                pages.append(item)
                new_items += 1

            if new_items == 0:
                break

            links = data.get("_links", {})
            next_link = links.get("next") if isinstance(links, dict) else None
            if not next_link:
                break

            next_cursor = None
            try:
                parsed = urlparse(next_link)
                query = parse_qs(parsed.query)
                if "cursor" in query and query["cursor"]:
                    next_cursor = query["cursor"][0]
            except (ValueError, TypeError, KeyError):
                next_cursor = None

            if not next_cursor:
                break

            if next_cursor in seen_cursors:
                break

            seen_cursors.add(next_cursor)
            cursor = next_cursor

        return pages


def build_tree(pages: list[dict]) -> tuple[dict[str, dict], dict[str, str | None], dict[str, list[str]], list[str]]:
    page_map = {str(p["id"]): p for p in pages}
    parent: dict[str, str | None] = {pid: None for pid in page_map}
    children: dict[str, list[str]] = {pid: [] for pid in page_map}

    for pid, page in page_map.items():
        direct_parent = None
        for anc in reversed(page.get("ancestors", []) or []):
            anc_id = str(anc.get("id", ""))
            if anc_id in page_map:
                direct_parent = anc_id
                break
        parent[pid] = direct_parent
        if direct_parent is not None:
            children[direct_parent].append(pid)

    def by_title(pid: str) -> str:
        return (page_map[pid].get("title") or "").lower()

    roots = [pid for pid, p in parent.items() if p is None]
    roots.sort(key=by_title)

    for pid in children:
        children[pid].sort(key=by_title)

    return page_map, parent, children, roots


def collect_descendants(start_ids: list[str], children: dict[str, list[str]]) -> list[str]:
    result: list[str] = []
    stack = list(reversed(start_ids))

    while stack:
        current = stack.pop()
        result.append(current)
        for child in reversed(children.get(current, [])):
            stack.append(child)

    return result


def resolve_requested_spaces(client: ConfluenceSimpleClient, requested_spaces: list[str]) -> list[tuple[str, str, str]]:
    spaces = client.list_spaces()
    key_to_name = {str(s.get("key", "")): str(s.get("name", "")) for s in spaces if s.get("key")}
    alias_map = {"cs": "CN", "cn": "CN", "auto": "AUTO"}

    resolved: list[tuple[str, str, str]] = []
    used_keys: set[str] = set()

    for req in requested_spaces:
        req_l = req.lower()
        key = None

        direct_key = req.upper()
        if direct_key in key_to_name:
            key = direct_key

        if key is None and req_l in alias_map and alias_map[req_l] in key_to_name:
            key = alias_map[req_l]

        if key is None:
            for k, n in key_to_name.items():
                k_l = k.lower()
                n_l = n.lower()
                if req_l == k_l or req_l in n_l or n_l in req_l:
                    key = k
                    break

        if key is None:
            raise RuntimeError(f"Confluence-Space nicht gefunden für Anfrage '{req}'. Verfügbare Keys: {', '.join(sorted(key_to_name))}")

        if key in used_keys:
            continue

        used_keys.add(key)
        resolved.append((req, key, key_to_name[key]))

    return resolved


def main() -> int:
    load_dotenv(ROOT / ".env")

    required = ["CONFLUENCE_BASE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Fehlende Variablen: {', '.join(missing)}")

    client = ConfluenceSimpleClient(
        os.environ["CONFLUENCE_BASE_URL"],
        os.environ["CONFLUENCE_EMAIL"],
        os.environ["CONFLUENCE_API_TOKEN"],
    )

    lines: list[str] = []
    overall_pages = 0
    overall_books = 0
    overall_chapters = 0
    overall_seiten = 0

    lines.append("# Confluence-Struktur (Spaces: cs, auto)")
    lines.append("")

    resolved_spaces = resolve_requested_spaces(client, SPACES)

    for requested_space, resolved_space, space_name in resolved_spaces:
        pages = client.list_pages_in_space(resolved_space)
        page_map, _, children, books = build_tree(pages)

        effective_books = books
        if len(books) == 1:
            root_id = books[0]
            root_title = (page_map[root_id].get("title") or "").strip().lower()
            space_name_norm = (space_name or "").strip().lower()
            space_key_norm = (resolved_space or "").strip().lower()
            if root_title == space_name_norm or root_title == space_key_norm:
                first_level = children.get(root_id, [])
                if first_level:
                    effective_books = first_level

        total_space_pages = len(pages)
        total_space_books = len(effective_books)
        total_space_chapters = 0
        total_space_seiten = 0

        overall_pages += total_space_pages
        overall_books += total_space_books

        lines.append(f"## Space `{resolved_space}` – {space_name}")
        if requested_space.lower() != resolved_space.lower():
            lines.append(f"- Angefragt als: `{requested_space}`")
            lines.append("")
        lines.append("")
        lines.append(f"- Gesamtseiten im Space: **{total_space_pages}**")
        lines.append(f"- Bücher (Top-Level): **{total_space_books}**")
        lines.append("")

        for book_id in effective_books:
            book_title = page_map[book_id].get("title", "Untitled")
            chapter_ids = children.get(book_id, [])
            total_space_chapters += len(chapter_ids)

            book_seiten = 0
            for chapter_id in chapter_ids:
                seiten_ids = collect_descendants(children.get(chapter_id, []), children)
                book_seiten += len(seiten_ids)

            total_space_seiten += book_seiten

            lines.append(f"### Buch: {book_title}")
            lines.append(f"- Chapter: **{len(chapter_ids)}**")
            lines.append(f"- Seiten (unterhalb der Chapter): **{book_seiten}**")

            if not chapter_ids:
                lines.append("- _(Keine Chapter)_")
                lines.append("")
                continue

            for chapter_id in chapter_ids:
                chapter_title = page_map[chapter_id].get("title", "Untitled")
                seiten_ids = collect_descendants(children.get(chapter_id, []), children)

                lines.append(f"- Chapter: {chapter_title} (**{len(seiten_ids)} Seiten**)")
                if not seiten_ids:
                    lines.append("  - _(Keine Seiten)_")
                    continue

                for page_id in seiten_ids:
                    page_title = page_map[page_id].get("title", "Untitled")
                    lines.append(f"  - Seite: {page_title}")

            lines.append("")

        lines.append(f"- Kapitel gesamt: **{total_space_chapters}**")
        lines.append(f"- Seiten gesamt (unterhalb von Chaptern): **{total_space_seiten}**")
        lines.append("")
        lines.append("---")
        lines.append("")

        overall_chapters += total_space_chapters
        overall_seiten += total_space_seiten

    lines.append("## Gesamt über beide Spaces")
    lines.append("")
    lines.append(f"- Gesamtseiten (alle Confluence-Seiten): **{overall_pages}**")
    lines.append(f"- Bücher (Top-Level): **{overall_books}**")
    lines.append(f"- Chapter (Ebene 2): **{overall_chapters}**")
    lines.append(f"- Seiten (ab Ebene 3): **{overall_seiten}**")

    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")

    print(f"OUTPUT={OUTPUT_FILE}")
    print(f"TOTAL_PAGES={overall_pages}")
    print(f"TOTAL_BOOKS={overall_books}")
    print(f"TOTAL_CHAPTERS={overall_chapters}")
    print(f"TOTAL_SEITEN={overall_seiten}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
