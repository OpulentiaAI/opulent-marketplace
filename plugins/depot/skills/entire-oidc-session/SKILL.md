---
name: entire-oidc-session
description: Give a Depot CI job a short-lived Entire session for an Entire service account through Depot CI OIDC, with no stored Entire credential. Use when a Depot CI workflow must call Entire (clone or push an Entire repository, call the Entire API) as a service account such as opulent-managed-broker.
---

# Entire sessions from Depot CI OIDC

Entire trusts Depot CI's OIDC issuer (https://identity.depot.dev). A job with "id-token: write" requests an OIDC
token from the request credentials Depot CI injects (ACTIONS_ID_TOKEN_REQUEST_URL and
ACTIONS_ID_TOKEN_REQUEST_TOKEN). It exchanges that token at Entire's token endpoint for an "entire:sa-session"
token and runs one command with that session as ENTIRE_TOKEN. The Entire CLI and git-remote-entire read
ENTIRE_TOKEN directly. Nothing long-lived is stored in Depot, and the session expires on its own.

Files:

- scripts/mint-entire-session.sh does the exchange. It is the same file the Buildkite plugin ships. It never prints
  the tokens, never writes them to disk and never puts them on a command line: curl reads each credential from
  stdin. Only the command after "--" receives the session.
- templates/workflow.yml is a Depot CI workflow to copy into .depot/workflows/.

## One-time setup (an Entire org admin of opulent-managed)

The service account already exists: opulent-managed-broker, svc_01M6CJT6RC0J6TPA9CFPYYR4DR, in org
opulent-managed. It needs an OIDC binding that admits only the repository and branch that should act as it, and a
grant on only what that workflow needs.

1. Find Depot's provider id:
   entire api /api/v1/oidc-providers
   Use the provider whose issuer is https://identity.depot.dev. The listing also names the canonical attribute
   names you can pin.
2. Bind the repository. Depot CI tokens for Entire runs carry
   sub = spiffe://identity.depot.dev/org/<depot-org-id>/ci/entire/<namespace>/<owner>/<repo>/ref/<ref>/sandbox/<id>
   plus flat claims such as org_id, repository (the full et/... name) and ref. Pin the Depot organization, the
   repository and the ref (the full refs/heads/... name), and never the sandbox id, which changes on every job. Put the body in a file:
   {"providerId": "<provider id>", "attributeFilter": {"org_id": "<depot-org-id>", "repository": "et/opulent-managed/<repo>", "ref": "refs/heads/main"}}
   entire api -X POST /api/v1/service-accounts/svc_01M6CJT6RC0J6TPA9CFPYYR4DR/bindings --input binding.json
   Use the attribute names the provider listing shows if they differ from Depot's claim names above.
3. Grant the least role that works, on one project or repository:
   entire api -X POST /api/v1/service-accounts/svc_01M6CJT6RC0J6TPA9CFPYYR4DR/grants -F resourceType=project -F resourceId=<id> -f role=reader

Opulent's production broker does not use this account yet. Moving it off the personal login is a separate
decision (DEF-151). This template does not change it.

## In a workflow

Copy scripts/mint-entire-session.sh into the repository and templates/workflow.yml into .depot/workflows/. Keep
"id-token: write" in the job's permissions. Then:

- mint-entire-session.sh --provider depot --check proves the exchange and that Entire's control plane accepts the
  session.
- mint-entire-session.sh --provider depot -- <command> runs the command with ENTIRE_TOKEN set.

Configuration lives in the job's env, never in secrets: ENTIRE_SERVICE_ACCOUNT_ID (required), and, only when Entire
tells you to change them, ENTIRE_OIDC_AUDIENCE (default https://us.auth.entire.io), ENTIRE_TOKEN_URL (default
https://us.auth.entire.io/oauth/token) and ENTIRE_API_URL (default https://us.console.entire.io).

## When it fails

- Exit 69 means the job has no OIDC request credentials (add "id-token: write"), Depot refused the token, or
  Entire did not answer.
- Exit 77 means Entire refused the exchange or the session. The binding does not match this job's claims, or the
  account lacks a grant. The error names the OAuth error code only.
- Exit 64 means the job's configuration is malformed. The message names the variable.

## What is verified

The exchange is tested against a mock Entire endpoint and a mock Depot token endpoint
(tests/test_entire_oidc_session.py in the marketplace repo). The request follows Entire's published token
endpoint, which supports RFC 8693 token exchange and the entire:sa-session scope. Which form field selects the
service account (this template sends it as "audience") and the audience Entire expects on the Depot token are not
yet confirmed by a live run. No Depot account exists yet.
