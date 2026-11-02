# Convex

Uses the official `convex@1.49.0` stdio MCP server. Enabled tools are `status`,
`tables`, `data`, `functionSpec`, `logs`, and `insights`. Function execution,
one-off queries, and all environment-variable tools are disabled. The production
PII flag permits read-only diagnostics; these reads can still expose private data.

`logs` performs one fetch and returns `entries` and `newCursor`. It supports
`status` (`all`, `success`, `failure`), `entriesLimit`, `tokensLimit`, and `jsonl`.
It does not tail logs or subscribe to events. Limits can omit older entries within
a batch; cursor progress is not proof of complete historical coverage.

## Installation contract

This catalog entry is unavailable until isolated MCP execution, Secret binding,
and deployment-host grants are implemented. The current shared-UID MCP broker
does not isolate a deploy key from other MCP processes, and the per-child isolated
profile has no wired outbound network. The runtime must refuse launch rather than
inject a deploy key into that broker. No live connection has been verified.

- Bind `CONVEX_DEPLOY_KEY` to an existing Secret **name**, never a literal key in
  the manifest or installation settings. Resolve it only into this trusted MCP
  child process; never fall back to an inherited host key or export it to a shell.
- Select the deployment at installation time. Require a deployment-scoped key,
  reject project/preview keys, and fail closed if its deployment does not match
  the selected target. The CLI prioritizes deployment keys over CLI selectors.
- Grant `api.convex.dev` plus the validated exact hostname of the selected
  deployment. The latter is added by the runtime, not a wildcard or an arbitrary
  manifest URL. Custom deployment domains require the same identity validation.
- Pass the actual project's directory to `status`. Its returned selector is used
  by subsequent tools. Do not treat a filesystem path as deployment authorization.

Top-level shell secrets must continue to reject `CONVEX_*`. This plugin does not
deploy, change environment variables, or grant permission to mutate production.

## Provenance

Capabilities and flags verified against the npm `convex@1.49.0` source:
`src/cli/mcp.ts`, `src/cli/lib/mcp/tools/index.ts`, `logs.ts`, and
`src/cli/lib/deploymentSelection.ts`.
First-party documentation: https://docs.convex.dev/cli/reference/mcp.
The logo is converted from https://www.convex.dev/favicon.ico.
