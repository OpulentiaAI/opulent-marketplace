"""Mock tests for the Entire OIDC session template that the Buildkite and Depot plugins ship.

Run: python3 -m unittest discover -s tests -v

A loopback server stands in for Entire's token endpoint, Entire's control plane and Depot's OIDC token endpoint, and
a fake buildkite-agent stands in for the Buildkite agent. A curl shim records every command line, so the tests prove
that no token reaches argv, stdout or stderr and that only the command after "--" receives the minted session.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted(ROOT.glob("plugins/*/skills/entire-oidc-session/scripts/mint-entire-session.sh"))
ACCOUNT = "svc_01M6CJT6RC0J6TPA9CFPYYR4DR"


def jwt(claims: dict) -> str:
    part = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
    return part({"alg": "RS256"}) + "." + part(claims) + "." + part({"sig": claims["jti"]})


CI_TOKEN = jwt({"iss": "https://agent.buildkite.com", "sub": "organization:opulent:pipeline:broker", "jti": "ci"})
DEPOT_CI_TOKEN = jwt({"iss": "https://identity.depot.dev", "sub": "spiffe://identity.depot.dev/org/x/ci/entire/et/opulent-managed/x", "jti": "depot"})
SESSION = jwt({"iss": "https://us.auth.entire.io", "sub": ACCOUNT, "aud": ["https://us.console.entire.io"], "jti": "session"})
REQUEST_TOKEN = "depot-request-credential-0123456789"
SECRETS = (CI_TOKEN, DEPOT_CI_TOKEN, SESSION, REQUEST_TOKEN)


class Entire(http.server.BaseHTTPRequestHandler):
    exchanges: list[dict] = []
    refuse_exchange = False
    refuse_session = False

    def log_message(self, *args: object) -> None:
        pass

    def reply(self, status: int, body: dict | None = None) -> None:
        data = json.dumps(body or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        if self.path != "/oauth/token":
            return self.reply(404)
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        form = {key: values[0] for key, values in form.items()}
        form["client"] = base64.b64decode(self.headers.get("Authorization", "Basic ").split(" ", 1)[1]).decode()
        Entire.exchanges.append(form)
        if Entire.refuse_exchange or form.get("subject_token") not in (CI_TOKEN, DEPOT_CI_TOKEN):
            return self.reply(400, {"error": "invalid_grant", "error_description": "no binding matches " + form.get("subject_token", "")})
        self.reply(200, {"access_token": SESSION, "issued_token_type": "urn:ietf:params:oauth:token-type:access_token", "token_type": "Bearer", "expires_in": 900})

    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/v1/clusters":
            ok = self.headers.get("Authorization") == "Bearer " + SESSION and not Entire.refuse_session
            return self.reply(200 if ok else 401, {"clusters": []} if ok else {"error": "unauthorized"})
        if url.path == "/depot/token":
            query = urllib.parse.parse_qs(url.query)
            if self.headers.get("Authorization") != "bearer " + REQUEST_TOKEN or query.get("audience") != ["https://us.auth.entire.io"] or query.get("run") != ["7"]:
                return self.reply(403)
            return self.reply(200, {"value": DEPOT_CI_TOKEN})
        self.reply(404)


FAKE_AGENT = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG/agent-argv"
case "$1 $2" in
  "oidc request-token") printf '%s' "$FAKE_CI_TOKEN" ;;
  "redactor add") [ "$3" = --help ] && exit 0; cat > "$FAKE_LOG/redacted" ;;
  *) exit 2 ;;
esac
"""

CURL_SHIM = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG/curl-argv"
exec "$REAL_CURL" "$@"
"""


@unittest.skipUnless(SCRIPTS and shutil.which("curl") and shutil.which("bash"), "needs the template, bash and curl")
class MintEntireSession(unittest.TestCase):
    server: http.server.ThreadingHTTPServer

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Entire)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def setUp(self) -> None:
        Entire.exchanges = []
        Entire.refuse_exchange = False
        Entire.refuse_session = False
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work)
        bin_dir = self.work / "bin"
        bin_dir.mkdir()
        for name, body in (("buildkite-agent", FAKE_AGENT), ("curl", CURL_SHIM)):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        self.env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REAL_CURL": shutil.which("curl"),
            "FAKE_LOG": str(self.work),
            "FAKE_CI_TOKEN": CI_TOKEN,
            "ENTIRE_SERVICE_ACCOUNT_ID": ACCOUNT,
            "ENTIRE_TOKEN_URL": self.base + "/oauth/token",
            "ENTIRE_API_URL": self.base,
            "ENTIRE_OIDC_ALLOW_LOOPBACK_HTTP": "1",
        }

    def run_script(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(SCRIPTS[0]), *args], env={**self.env, **(env or {})}, capture_output=True, text=True, timeout=60)

    def child(self) -> list[str]:
        return ["--", "bash", "-c", 'printf %s "$ENTIRE_TOKEN" | sha256sum | cut -d" " -f1 > "$FAKE_LOG/child"']

    def assert_no_secret_leaked(self, result: subprocess.CompletedProcess[str]) -> None:
        logs = [result.stdout, result.stderr] + [path.read_text() for path in self.work.glob("*-argv")]
        for secret in SECRETS:
            for log in logs:
                self.assertNotIn(secret, log)

    def test_every_plugin_ships_the_same_template(self) -> None:
        self.assertGreaterEqual(len(SCRIPTS), 1)
        for script in SCRIPTS:
            self.assertEqual(script.read_bytes(), SCRIPTS[0].read_bytes(), script)
            self.assertTrue(os.access(script, os.X_OK), script)

    def test_buildkite_job_mints_a_session_and_hands_it_only_to_the_command(self) -> None:
        result = self.run_script("--provider", "buildkite", "--check", *self.child())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("minted an Entire session for " + ACCOUNT + " through buildkite OIDC", result.stdout)
        self.assertEqual((self.work / "child").read_text().strip(), hashlib.sha256(SESSION.encode()).hexdigest())
        self.assertEqual((self.work / "redacted").read_text(), SESSION)
        self.assertIn("oidc request-token --audience https://us.auth.entire.io --lifetime 300", (self.work / "agent-argv").read_text())
        [exchange] = Entire.exchanges
        self.assertEqual(exchange, {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "scope": "entire:sa-session",
            "audience": ACCOUNT,
            "subject_token": CI_TOKEN,
            "client": "entire-cli:",
        })
        self.assert_no_secret_leaked(result)

    def test_depot_job_mints_a_session_from_its_oidc_request_credentials(self) -> None:
        env = {"ACTIONS_ID_TOKEN_REQUEST_URL": self.base + "/depot/token?run=7", "ACTIONS_ID_TOKEN_REQUEST_TOKEN": REQUEST_TOKEN}
        result = self.run_script("--check", *self.child(), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("through depot OIDC", result.stdout)
        self.assertEqual(Entire.exchanges[0]["subject_token"], DEPOT_CI_TOKEN)
        self.assertEqual((self.work / "child").read_text().strip(), hashlib.sha256(SESSION.encode()).hexdigest())
        self.assertFalse((self.work / "agent-argv").exists())
        self.assert_no_secret_leaked(result)

    def test_depot_job_without_id_token_permission_stops_before_any_request(self) -> None:
        result = self.run_script("--provider", "depot", *self.child())
        self.assertEqual(result.returncode, 69)
        self.assertIn("id-token: write", result.stderr)
        self.assertEqual(Entire.exchanges, [])

    def test_a_refused_exchange_never_runs_the_command_or_echoes_the_token(self) -> None:
        Entire.refuse_exchange = True
        result = self.run_script("--provider", "buildkite", *self.child())
        self.assertEqual(result.returncode, 77)
        self.assertIn("HTTP 400, invalid_grant", result.stderr)
        self.assertFalse((self.work / "child").exists())
        self.assert_no_secret_leaked(result)

    def test_check_fails_when_the_control_plane_refuses_the_session(self) -> None:
        Entire.refuse_session = True
        result = self.run_script("--provider", "buildkite", "--check", *self.child())
        self.assertEqual(result.returncode, 77)
        self.assertFalse((self.work / "child").exists())
        self.assert_no_secret_leaked(result)

    def test_check_alone_exits_after_verifying(self) -> None:
        result = self.run_script("--provider", "buildkite", "--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inputs_are_refused_before_any_request(self) -> None:
        cases = [
            ({"ENTIRE_SERVICE_ACCOUNT_ID": "opulent-managed-broker"}, "ENTIRE_SERVICE_ACCOUNT_ID"),
            ({"ENTIRE_OIDC_ALLOW_LOOPBACK_HTTP": ""}, "not a plain https URL"),
            ({"ENTIRE_TOKEN_URL": "https://user:pass@us.auth.entire.io/oauth/token"}, "not a plain https URL"),
            ({"ENTIRE_OIDC_AUDIENCE": "https://us.auth.entire.io\nheader = x"}, "malformed"),
        ]
        for env, message in cases:
            with self.subTest(env=env):
                result = self.run_script("--provider", "buildkite", *self.child(), env=env)
                self.assertEqual(result.returncode, 64)
                self.assertIn(message, result.stderr)
        self.assertEqual(self.run_script("--provider", "buildkite").returncode, 64)
        self.assertEqual(self.run_script(*self.child(), env={"BUILDKITE_JOB_ID": ""}).returncode, 64)
        self.assertEqual(Entire.exchanges, [])


if __name__ == "__main__":
    unittest.main()
