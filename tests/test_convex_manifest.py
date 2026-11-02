import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate", ROOT / "scripts/validate.py")
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)


class ConvexManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "plugins/convex/.opulent-plugin/plugin.json").read_text())
        self.server = self.manifest["mcpServers"]["convex"]

    def test_pinned_read_only_server(self):
        self.assertEqual(self.server["command"], "npx")
        self.assertEqual(self.server["args"][:4], ["-y", "convex@1.49.0", "mcp", "start"])
        self.assertIn("--cautiously-allow-production-pii", self.server["args"])
        self.assertNotIn("--dangerously-enable-production-deployments", self.server["args"])
        disabled = self.server["args"][self.server["args"].index("--disable-tools") + 1]
        upstream = {"status", "tables", "data", "functionSpec", "logs", "insights", "run", "runOneoffQuery", "envGet", "envList", "envSet", "envRemove"}
        self.assertEqual(upstream - set(disabled.split(",")), {"status", "tables", "data", "functionSpec", "logs", "insights"})

    def test_secret_reference_and_generic_hosts(self):
        self.assertEqual(self.server["env"], {"CONVEX_DEPLOY_KEY": "${CONVEX_DEPLOY_KEY}"})
        self.assertEqual(self.server["allowedHosts"], ["api.convex.dev"])
        errors = []
        validate.check_server("convex", "convex", self.server, errors)
        self.assertEqual(errors, [])
        validate.check_secrets("convex", {"CONVEX_DEPLOY_KEY": {"description": "Forbidden shell export"}}, set(), errors)
        self.assertTrue(errors)

    def test_catalog_registration(self):
        root = json.loads((ROOT / ".opulent-plugin/plugin.json").read_text())
        self.assertEqual(root["optionalPlugins"].count("./plugins/convex"), 1)
        bundle = json.loads((ROOT / "catalog/bundles/convex.json").read_text())
        manifest = next(file for file in bundle["files"] if file["path"] == ".opulent-plugin/plugin.json")
        self.assertEqual(json.loads(manifest["content"]), self.manifest)


if __name__ == "__main__":
    unittest.main()
