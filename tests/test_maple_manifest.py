import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate", ROOT / "scripts/validate.py")
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)

ENDPOINT = "https://api.maple.dev/mcp"


def manifest(slug):
    return json.loads((ROOT / f"plugins/{slug}/.opulent-plugin/plugin.json").read_text())


class MapleManifestTest(unittest.TestCase):
    def test_oauth_listing_declares_only_the_endpoint(self):
        server = manifest("maple")["mcpServers"]["maple"]
        self.assertEqual(server, {"url": ENDPOINT})
        errors = []
        validate.check_server("maple", "maple", server, errors)
        self.assertEqual(errors, [])

    def test_api_key_listing_sends_one_bearer_credential(self):
        server = manifest("maple-api-key")["mcpServers"]["maple-api-key"]
        self.assertEqual(server["url"], ENDPOINT)
        self.assertEqual(server["headers"], {"Authorization": "Bearer ${MAPLE_API_KEY}"})
        errors = []
        validate.check_server("maple-api-key", "maple-api-key", server, errors)
        self.assertEqual(errors, [])

    def test_http_servers_cannot_declare_a_tool_allowlist(self):
        errors = []
        validate.check_server("maple", "maple", {"url": ENDPOINT, "allowedTools": ["list_services"]}, errors)
        self.assertTrue(errors)

    def test_descriptions_warn_about_write_tools(self):
        for slug in ("maple", "maple-api-key"):
            description = manifest(slug)["description"]
            self.assertIn("write tools", description)
            self.assertIn("allows every tool", description)
            self.assertIn("Limit tools (advanced)", description)

    def test_catalog_registration_carries_no_credential(self):
        root = json.loads((ROOT / ".opulent-plugin/plugin.json").read_text())
        catalog = json.loads((ROOT / "catalog.json").read_text())
        for slug in ("maple", "maple-api-key"):
            self.assertEqual(root["optionalPlugins"].count(f"./plugins/{slug}"), 1)
            listing = next(item for item in catalog["plugins"] if item["name"] == slug)
            self.assertEqual(listing["mcpServers"], [slug])
            self.assertEqual(listing["logo"]["mediaType"], "image/svg+xml")
            bundle_text = (ROOT / f"catalog/bundles/{slug}.json").read_text()
            self.assertIsNone(re.search(r"maple_(ak|sk|pk)_[A-Za-z0-9]", bundle_text))
            bundle = json.loads(bundle_text)
            file = next(item for item in bundle["files"] if item["path"] == ".opulent-plugin/plugin.json")
            self.assertEqual(json.loads(file["content"]), manifest(slug))


if __name__ == "__main__":
    unittest.main()
