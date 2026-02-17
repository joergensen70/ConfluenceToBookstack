import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import confluence_to_bookstack_migration as m


def main():
    needle = "netzwerkkonfiguration"
    cfg = m.load_config_from_env()

    bs = m.BookStackClient(cfg.bookstack_base_url, cfg.bookstack_token_id, cfg.bookstack_token_secret)
    books = m.get_all_bookstack_items(bs, "/api/books")
    book_hits = [b for b in books if needle in (b.get("name", "").lower())]
    print(f"BookStack Book Treffer: {len(book_hits)}")
    for book in book_hits:
        print(f"- id={book.get('id')} name={book.get('name')}")

    target_book_name = "Moved to bookstack"
    target_book = next((b for b in books if b.get("name") == target_book_name), None)
    if target_book:
        print(f"BookStack Book exakte Uebereinstimmung: id={target_book.get('id')} name={target_book.get('name')}")
    else:
        print(f"BookStack Book exakte Uebereinstimmung: nicht gefunden ({target_book_name})")

    pages = m.get_all_bookstack_items(bs, "/api/pages")
    hits = [p for p in pages if needle in (p.get("name", "").lower())]
    print(f"BookStack Seiten Treffer: {len(hits)}")
    for page in hits:
        print(
            f"- id={page.get('id')} book_id={page.get('book_id')} chapter_id={page.get('chapter_id')} name={page.get('name')}"
        )

    chapters = m.get_all_bookstack_items(bs, "/api/chapters")
    if target_book:
        target_book_id = int(target_book.get("id"))
        target_chapters = [c for c in chapters if int(c.get("book_id", -1)) == target_book_id]
        print(f"Kapitel im Book '{target_book_name}': {len(target_chapters)}")
        for chapter in target_chapters:
            print(f"- id={chapter.get('id')} name={chapter.get('name')}")

    chapter_hits = []
    for chapter in chapters:
        if needle in (chapter.get("name", "").lower()):
            chapter_hits.append(chapter)
    print(f"BookStack Kapitel Treffer: {len(chapter_hits)}")
    for chapter in chapter_hits:
        print(f"- id={chapter.get('id')} book_id={chapter.get('book_id')} name={chapter.get('name')}")

    content_title = f"{needle} (kapitelinhalt)"
    content_hits = [
        p
        for p in pages
        if content_title in (p.get("name", "").lower())
    ]
    print(f"BookStack Kapitelinhalt Treffer: {len(content_hits)}")
    for page in content_hits:
        print(
            f"- id={page.get('id')} book_id={page.get('book_id')} chapter_id={page.get('chapter_id')} name={page.get('name')}"
        )

    conf = m.ConfluenceClient(cfg.confluence_base_url, cfg.confluence_email, cfg.confluence_api_token)
    space_key = cfg.confluence_space_key
    conf_pages = conf.list_pages_in_space(space_key)
    conf_hits = [p for p in conf_pages if needle in (p.get("title", "").lower())]
    print(f"Confluence Treffer (Space {space_key}): {len(conf_hits)}")
    for page in conf_hits:
        ancestors = page.get("ancestors", []) or []
        trail = " / ".join([a.get("title", "") for a in ancestors if a.get("title")])
        print(f"- id={page.get('id')} title={page.get('title')} ancestors={trail}")


if __name__ == "__main__":
    main()
