// The Depot plugin's connection check, run exactly as its manifest declares, against a mock Depot API.
//
// Run: node --test tests/*.test.mjs
//
// Opulent marks the Depot plugin connected only when its connectionCheck exits 0 with the owner's DEPOT_TOKEN in the
// environment. This test runs the pinned @depot/cli from the manifest with DEPOT_API_URL pointed at a loopback HTTP/2
// server that answers the Connect ListProjects call. It proves the check passes for an accepted token, fails for a
// refused or missing one, and that the token travels only as a bearer header, never in argv.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import http2 from "node:http2";
import { after, before, test } from "node:test";

const manifestPath = new URL("../plugins/depot/.opulent-plugin/plugin.json", import.meta.url);
const present = existsSync(manifestPath) && spawnSync("npx", ["--version"]).status === 0;
const check = present ? JSON.parse(readFileSync(manifestPath, "utf8")).connectionCheck : null;
const accepted = "depot_org_accepted_0123456789abcdef";
const listProjects = "/depot.cli.v1beta1.ProjectsService/ListProjects";
let seen = [];
let server;
let url;

before(async () => {
  if (!present) return;
  server = http2.createServer((request, response) => {
    seen.push([request.url, request.headers.authorization ?? null]);
    request.resume();
    request.on("end", () => {
      if (request.url !== listProjects) return response.writeHead(404).end();
      if (request.headers.authorization !== "Bearer " + accepted) return response.writeHead(401, { "content-type": "application/json" }).end(JSON.stringify({ code: "unauthenticated", message: "Invalid token" }));
      response.writeHead(200, { "content-type": "application/proto" }).end();
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  url = "http://127.0.0.1:" + server.address().port;
});
after(() => server?.close());

function runCheck(token) {
  seen = [];
  const env = { PATH: process.env.PATH, HOME: mkdtempSync(join(tmpdir(), "depot-home-")), npm_config_cache: process.env.npm_config_cache ?? join(homedir(), ".npm"), DEPOT_API_URL: url, ...(token === null ? {} : { DEPOT_TOKEN: token }) };
  return new Promise((resolve) => {
    const child = spawn(check.command, check.args, { env, stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    const timer = setTimeout(() => child.kill("SIGKILL"), (check.timeoutSeconds + 120) * 1000);
    child.on("close", (status) => { clearTimeout(timer); resolve({ status, stderr }); });
  });
}

test("the check is the pinned Depot CLI listing projects, reaching only api.depot.dev", { skip: !present }, () => {
  assert.equal(check.command, "npx");
  assert.deepEqual(check.args, ["-y", "@depot/cli@0.0.1-cli.2.103.6", "projects", "list", "--output", "json"]);
  assert.deepEqual(check.allowedHosts, ["api.depot.dev"]);
});

test("an accepted token passes the check and travels only as a bearer header", { skip: !present, timeout: 300_000 }, async () => {
  const result = await runCheck(accepted);
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(seen, [[listProjects, "Bearer " + accepted]]);
  assert.ok(!check.args.join(" ").includes(accepted));
});

test("a refused token fails the check", { skip: !present, timeout: 300_000 }, async () => {
  const result = await runCheck("depot_org_revoked_0123456789abcdef");
  assert.notEqual(result.status, 0);
  assert.deepEqual(seen.map(([path]) => path), [listProjects]);
});

test("a missing token fails the check before any request", { skip: !present, timeout: 300_000 }, async () => {
  const result = await runCheck(null);
  assert.notEqual(result.status, 0);
  assert.deepEqual(seen, []);
});
