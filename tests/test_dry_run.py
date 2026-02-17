import os
import re
import tempfile
import unittest
from unittest.mock import patch

import confluence_to_bookstack_migration as mig


class FakeConfluenceClient:
    pages = []

    def __init__(self, base_url, email, api_token):
        self.base_url = base_url
        self.email = email
        self.api_token = api_token

    def get_space_name(self, space_key):
        return "Space Name"

    def list_pages_in_space(self, space_key):
        return list(self.pages)

    def get_page_detail(self, page_id):
        for page in self.pages:
            if str(page.get("id")) == str(page_id):
                return page
        return {
            "id": str(page_id),
            "title": "",
            "ancestors": [],
            "body": {"view": {"value": ""}, "storage": {"value": ""}},
        }

    def _has_meaningful_content(self, html_text):
        if not html_text or not html_text.strip():
            return False
        content = re.sub(r"<p>\s*</p>|<br\s*/?>|<div>\s*</div>", "", html_text.strip())
        has_text = bool(re.search(r"[a-zA-Z0-9]", content))
        has_images = bool(re.search(r"<img", content, re.IGNORECASE))
        return has_text or has_images


class FakeBookStackClient:
    last_instance = None

    def __init__(self, base_url, token_id, token_secret):
        self.base_url = base_url
        self.token_id = token_id
        self.token_secret = token_secret
        FakeBookStackClient.last_instance = self

    def _trim_name(self, name, context):
        return name

    def __getattr__(self, name):
        raise AssertionError(f"BookStack method should not be called in dry-run: {name}")


def build_config():
    return mig.Config(
        confluence_base_url="https://example.atlassian.net",
        confluence_email="user@example.com",
        confluence_api_token="token",
        confluence_space_key="SPACE",
        bookstack_base_url="https://bookstack.example.com",
        bookstack_token_id="token_id",
        bookstack_token_secret="token_secret",
        book_name_prefix="Confluence - ",
    )


class DryRunTests(unittest.TestCase):
    def setUp(self):
        FakeConfluenceClient.pages = [
            {
                "id": "1",
                "title": "Space Name",
                "ancestors": [],
                "body": {"view": {"value": ""}, "storage": {"value": ""}},
            },
            {
                "id": "2",
                "title": "Book A",
                "ancestors": [{"id": "1"}],
                "body": {"view": {"value": "<p>Alpha</p>"}, "storage": {"value": ""}},
            },
            {
                "id": "3",
                "title": "Book B",
                "ancestors": [{"id": "1"}],
                "body": {"view": {"value": "<p>Beta</p>"}, "storage": {"value": ""}},
            },
        ]

    @patch("confluence_to_bookstack_migration.ConfluenceClient", FakeConfluenceClient)
    @patch("confluence_to_bookstack_migration.BookStackClient", FakeBookStackClient)
    def test_dry_run_creates_overview_file(self):
        config = build_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            overview_path = os.path.join(tmpdir, "overview.md")
            migrator = mig.Migrator(
                config,
                space_key="SPACE",
                dry_run=True,
                auto_confirm=True,
                overview_only=False,
                overview_file=overview_path,
            )
            migrator.run()

            self.assertTrue(os.path.exists(overview_path))
            with open(overview_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("Confluence Migrations", content)
            self.assertIn("### Buch: Book A", content)

    @patch("confluence_to_bookstack_migration.ConfluenceClient", FakeConfluenceClient)
    @patch("confluence_to_bookstack_migration.BookStackClient", FakeBookStackClient)
    def test_build_structure_skips_root_container(self):
        config = build_config()
        migrator = mig.Migrator(config, space_key="SPACE", dry_run=True, auto_confirm=True)
        page_map, children, top_level = migrator._build_structure(
            FakeConfluenceClient.pages,
            "Space Name",
        )
        self.assertEqual(top_level, ["2", "3"])
        self.assertEqual(children.get("1"), ["2", "3"])
        self.assertIn("2", page_map)

    @patch("confluence_to_bookstack_migration.ConfluenceClient", FakeConfluenceClient)
    @patch("confluence_to_bookstack_migration.BookStackClient", FakeBookStackClient)
    def test_overview_only_skips_bookstack_calls(self):
        config = build_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            overview_path = os.path.join(tmpdir, "overview.md")
            migrator = mig.Migrator(
                config,
                space_key="SPACE",
                dry_run=False,
                auto_confirm=True,
                overview_only=True,
                overview_file=overview_path,
            )
            migrator.run()


if __name__ == "__main__":
    unittest.main()
