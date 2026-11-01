---
name: entire-oidc-session
description: Give a Buildkite job a short-lived Entire session for an Entire service account through Buildkite OIDC, with no stored Entire credential. Use when a pipeline step must call Entire (clone or push an Entire repository, call the Entire API) as a service account such as opulent-managed-broker.
---

# Entire sessions from Buildkite OIDC

Entire trusts Buildkite's OIDC issuer (https://agent.buildkite.com). A job asks its agent for an OIDC token,
exchanges it at Entire's token endpoint for an "entire:sa-session" token, and runs one command with that session as
ENTIRE_TOKEN. The Entire CLI and git-remote-entire read ENTIRE_TOKEN directly. Nothing long-lived is stored in
Buildkite, and the session expires on its own.

Files:

- scripts/mint-entire-session.sh does the exchange. It never prints the tokens, never writes them to disk and
  never puts them on a command line: curl reads each credential from stdin. Only the command after "--" receives
  the session, and on Buildkite the session is also added to the job log redactor.
- templates/pipeline.yml is a step to copy into a pipeline.

## One-time setup (an Entire org admin of opulent-managed)

The service account already exists: opulent-managed-broker, svc_01M6CJT6RC0J6TPA9CFPYYR4DR, in org
opulent-managed. It needs an OIDC binding that admits only the pipeline that should act as it, and a grant on
only what that pipeline needs.

1. Find Buildkite's provider id:
   entire api /api/v1/oidc-providers
   Use the provider whose issuer is https://agent.buildkite.com. The listing also names the canonical attribute
   names you can pin.
2. Bind the pipeline. Pin at least the organization and the pipeline, so another Buildkite org or pipeline can
   never mint this account's session. Put the body in a file and pass it with --input:
   {"providerId": "<provider id>", "attributeFilter": {"organization_slug": "opulent", "pipeline_slug": "<pipeline>"}}
   entire api -X POST /api/v1/service-accounts/svc_01M6CJT6RC0J6TPA9CFPYYR4DR/bindings --input binding.json
   Use the attribute names the provider listing shows if they differ from the Buildkite claim names above.
3. Grant the least role that works, on one project or repository:
   entire api -X POST /api/v1/service-accounts/svc_01M6CJT6RC0J6TPA9CFPYYR4DR/grants -F resourceType=project -F resourceId=<id> -f role=reader

Opulent's production broker does not use this account yet. Moving it off the personal login is a separate
decision (DEF-151). This template does not change it.

## In a pipeline

Copy scripts/mint-entire-session.sh into the repository (for example .buildkite/scripts/) and add the step in
templates/pipeline.yml. Then:

- mint-entire-session.sh --check proves the exchange and that Entire's control plane accepts the session.
- mint-entire-session.sh -- <command> runs the command with ENTIRE_TOKEN set, for example
  mint-entire-session.sh -- entire auth status, or a git clone of an entire:// remote.

Configuration lives in the step's env, never in secrets: ENTIRE_SERVICE_ACCOUNT_ID (required), and, only when
Entire tells you to change them, ENTIRE_OIDC_AUDIENCE (default https://us.auth.entire.io), ENTIRE_TOKEN_URL
(default https://us.auth.entire.io/oauth/token), ENTIRE_API_URL (default https://us.console.entire.io) and
ENTIRE_OIDC_LIFETIME (default 300 seconds).

## When it fails

- Exit 69 means the agent refused to issue the OIDC token, or Entire did not answer. Check the agent version
  (buildkite-agent oidc needs 3.42 or later) and the audience.
- Exit 77 means Entire refused the exchange or the session. The binding does not match this job's claims, or the
  account lacks a grant. The error names the OAuth error code only.
- Exit 64 means the step's configuration is malformed. The message names the variable.

## What is verified

The exchange is tested against a mock Entire endpoint (tests/test_entire_oidc_session.py in the marketplace repo).
The request follows Entire's published token endpoint, which supports RFC 8693 token exchange and the
entire:sa-session scope. Which form field selects the service account (this template sends it as "audience") and
the audience Entire expects on the Buildkite token are not yet confirmed by a live run. Confirm both on the first
run and adjust ENTIRE_OIDC_AUDIENCE if Entire refuses it.
