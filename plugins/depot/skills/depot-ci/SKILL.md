---
name: depot-ci
description: Run, inspect and debug Depot CI workflows with the pinned Depot CLI. Use when the user asks to run CI against local changes, why a Depot CI run failed, for a run's status or logs, or to retry, rerun, cancel or dispatch a Depot CI workflow.
---

# Depot CI

The Depot plugin exports the owner's Depot API token as DEPOT_TOKEN in the shell, filled from Customize →
Marketplace → Depot (a value sealed in Opulent's vault, or an op:// 1Password reference). The Depot CLI reads it
from the environment. Never pass it with --token, never echo it, and never ask for it in chat.

Run the CLI pinned, exactly as the plugin's connection check does:

    npx -y @depot/cli@0.0.1-cli.2.103.6 <command>

Below, "depot" means that command line.

## Find the run

- depot ci run list lists recent runs. depot ci status <run-id> --output json shows a run's workflows, jobs and
  attempts.
- When the token belongs to more than one organization, add --org <org-id> (depot org list shows them).
- Entire repositories are named <namespace>/<owner>/<name>: et/ for a repository hosted on Entire, gh/ for a GitHub
  mirror. Pass --forge entire --repo et/<owner>/<name> when the checkout has more than one forge remote.

## Debug a failure

1. depot ci diagnose --run <run-id> --output json gives Depot's bounded failure context for the failed jobs.
2. depot ci logs <job-id> (or <run-id> --job <key>) reads the logs. Quote the lines that explain the failure.
3. Fix the code, then run the workflow against the working tree without pushing:
   depot ci run --workflow .depot/workflows/<file>.yml --job <key>
   Add --follow to stream logs. Never use --ssh or --ssh-after-step: they need an interactive terminal.
4. depot ci status <run-id> --wait --output json waits for the result. It exits 0 for a finished run and 1 for a
   failed or cancelled one.

## Writes need the user's request

depot ci run, dispatch, rerun, retry and cancel start or stop real compute. depot ci secrets and depot ci vars
change the organization's CI configuration. Use them only when the user asked, and name the repository, workflow
and ref first. depot ci migrate rewrites workflow files in the checkout, so show the diff before committing.

## When the token is refused

"unauthenticated" or "missing API token" means DEPOT_TOKEN is missing, expired or revoked. Tell the user to
reconnect Depot in Customize → Marketplace. Do not run depot login: it is interactive and would store a second
credential on the machine.
