import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate

CHECK = {
    "command": "npx",
    "args": ["-y", "@depot/cli@2.101.0", "projects", "list", "--output", "json"],
    "allowedHosts": ["api.depot.dev"],
    "timeoutSeconds": 60,
}
SECRETS = {"DEPOT_TOKEN": {"description": "Depot API token.", "optional": False}}


class LocalPluginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original = validate.PLUGINS
        validate.PLUGINS = Path(self.tmp.name)
        self.addCleanup(setattr, validate, "PLUGINS", self.original)

    def errors(self, manifest: dict, slug: str = "depot") -> list[str]:
        directory = validate.PLUGINS / slug / ".opulent-plugin"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "plugin.json").write_text(json.dumps({"name": slug, **manifest}))
        errors: list[str] = []
        validate.check_local_plugin(slug, {slug}, errors)
        return errors

    def test_valid_secrets_with_check(self) -> None:
        self.assertEqual(self.errors({"secrets": SECRETS, "connectionCheck": CHECK}), [])

    def test_secrets_beside_mcp_server(self) -> None:
        server = {"depot": {"command": "npx", "args": ["-y", "depot-mcp@1.0.0"], "env": {"DEPOT_ORG": "${DEPOT_ORG}"}, "allowedHosts": []}}
        self.assertEqual(self.errors({"mcpServers": server, "secrets": SECRETS}), [])
        repeated = {"DEPOT_ORG": {"description": "Org."}}
        self.assertTrue(any("repeats an MCP server env name" in e for e in self.errors({"mcpServers": server, "secrets": repeated})))

    def test_refused_secret_names(self) -> None:
        for name in ("PATH", "OP_SERVICE_ACCOUNT_TOKEN", "LD_PRELOAD", "OPULENT_TOKEN", "lower"):
            with self.subTest(name=name):
                self.assertTrue(any("reserved environment name" in e for e in self.errors({"secrets": {name: {"description": "x"}}})))

    def test_secret_extra_key(self) -> None:
        errors = self.errors({"secrets": {"DEPOT_TOKEN": {"description": "x", "value": "nope"}}})
        self.assertTrue(any("only 'description' and 'optional'" in e for e in errors))

    def test_placeholder_in_check_args(self) -> None:
        check = {**CHECK, "args": [*CHECK["args"], "--token", "${DEPOT_TOKEN}"]}
        self.assertTrue(any("placeholders" in e for e in self.errors({"secrets": SECRETS, "connectionCheck": check})))

    def test_unpinned_check_package(self) -> None:
        for package in ("@depot/cli", "@depot/cli@latest", "@depot/cli@^2.0.0"):
            with self.subTest(package=package):
                check = {**CHECK, "args": ["-y", package, "projects", "list"]}
                self.assertTrue(any("pinned package" in e for e in self.errors({"secrets": SECRETS, "connectionCheck": check})))

    def test_check_matches_the_runtime_parser(self) -> None:
        refused = [
            {**CHECK, "args": ["--registry=https://evil.example", "-y", "@depot/cli@2.101.0"]},
            {**CHECK, "args": ["--package=evil", "@depot/cli@2.101.0"]},
            {**CHECK, "args": ["-y", "@depot/cli@v2.101.0"]},
            {**CHECK, "args": ["-y", "@depot/cli@2.101.0", "bad\x00arg"]},
            {**CHECK, "command": "uvx", "args": ["depot==1.2"]},
            {**CHECK, "command": "uvx", "args": ["--from", "evil", "depot==1.2.3"]},
        ]
        for check in refused:
            with self.subTest(args=check["args"]):
                self.assertNotEqual(self.errors({"secrets": SECRETS, "connectionCheck": check}), [])
        self.assertEqual(self.errors({"secrets": SECRETS, "connectionCheck": {**CHECK, "timeoutSeconds": 60.0}}), [])
        self.assertEqual(self.errors({"secrets": SECRETS, "connectionCheck": {**CHECK, "command": "uvx", "args": ["-q", "depot[cli]==1.2.3"]}}), [])
        self.assertTrue(any("description" in e for e in self.errors({"secrets": {"DEPOT_TOKEN": {"description": "   "}}})))

    def test_check_needs_secrets(self) -> None:
        server = {"depot": {"url": "https://mcp.depot.dev/mcp"}}
        self.assertTrue(any("needs secrets" in e for e in self.errors({"mcpServers": server, "connectionCheck": CHECK})))

    def test_secret_provider(self) -> None:
        provider = {"kind": "1password", "token": "OP_SERVICE_ACCOUNT_TOKEN"}
        self.assertEqual(self.errors({"secretProvider": provider}, slug="1password"), [])
        self.assertTrue(any("secretProvider" in e for e in self.errors({"secretProvider": {**provider, "token": "OTHER"}}, slug="1password")))
        self.assertTrue(any("secretProvider" in e for e in self.errors({"secretProvider": provider, "secrets": SECRETS})))
        self.assertTrue(any("no other secrets" in e for e in self.errors({"secretProvider": provider, "secrets": SECRETS}, slug="1password")))
        self.assertTrue(any("no other secrets" in e for e in self.errors({"secretProvider": provider, "mcpServers": {"1password": {"url": "https://example.com/mcp"}}}, slug="1password")))

    def test_neither_mcp_nor_secrets(self) -> None:
        self.assertTrue(any("mcpServers must declare exactly one server" in e for e in self.errors({})))

    def test_listing_carries_secrets_and_check(self) -> None:
        secrets = {"B_TOKEN": {"description": "b"}, "A_TOKEN": {"description": "a", "optional": True}}
        self.assertEqual(self.errors({"secrets": secrets}), [])
        listing, _ = validate.local_listing("depot")
        self.assertEqual(listing["secrets"], [
            {"name": "A_TOKEN", "description": "a", "optional": True},
            {"name": "B_TOKEN", "description": "b", "optional": False},
        ])
        self.assertNotIn("connectionCheck", listing)


if __name__ == "__main__":
    unittest.main()
