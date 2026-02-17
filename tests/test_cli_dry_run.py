import os
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

    def resolve_space_key(self, requested_space_key):
        return requested_space_key

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
        return bool(html_text and html_text.strip())


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


def build_env():
    return {
        "CONFLUENCE_BASE_URL": "https://acme.atlassian.net",
        "CONFLUENCE_EMAIL": "user@acme.local",
        "CONFLUENCE_API_TOKEN": "token",
        "CONFLUENCE_SPACE_KEY": "SPACE",
        "BOOKSTACK_BASE_URL": "https://bookstack.local",
        "BOOKSTACK_TOKEN_ID": "token_id",
        "BOOKSTACK_TOKEN_SECRET": "token_secret",
        "BOOKSTACK_BOOK_PREFIX": "Confluence - ",
    }


class CliDryRunTests(unittest.TestCase):
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
        ]

    @patch("confluence_to_bookstack_migration.ConfluenceClient", FakeConfluenceClient)
    @patch("confluence_to_bookstack_migration.BookStackClient", FakeBookStackClient)
    def test_cli_dry_run_generates_overview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            overview_path = os.path.join(tmpdir, "overview.md")
            env = build_env()
            argv = [
                "confluence_to_bookstack_migration.py",
                "--dry-run",
                "--yes",
                "--spaces",
                "SPACE",
                "--overview-file",
                overview_path,
            ]
            with patch.dict(os.environ, env, clear=True), patch("sys.argv", argv):
                exit_code = mig.main()

            self.assertEqual(exit_code, 0)
            self.assertTrue(os.path.exists(overview_path))


if __name__ == "__main__":
    unittest.main()
