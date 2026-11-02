---
name: buildkite-ci
description: Inspect and operate Buildkite pipelines, builds, jobs and logs through the Buildkite MCP server. Use when the user asks why a build failed, wants build or test status, or wants to trigger, retry, cancel or unblock a Buildkite build.
---

# Buildkite CI

The Buildkite plugin connects Buildkite's official remote MCP server (https://mcp.buildkite.com/direct) with the
owner's Buildkite API access token. The token is saved in Customize → Marketplace → Buildkite, either as a value
sealed in Opulent's vault or as an op:// 1Password reference. Never ask for the token in chat, and never print it.

## Start every session the same way

1. Call user_token_organization to learn the organization slug the token belongs to. Opulent's own account is
   "opulent". Almost every other tool needs that slug as org_slug.
2. Call list_skills once. Buildkite's server ships its own guides (for example, debugging a failed build or tuning
   search_logs), and load_skill returns one when the task matches.

## Read before you write

- Failures: get_build, then get_build_failure_summary or get_failed_executions, then read_logs or search_logs on
  the failing job. Quote the log lines that explain the failure instead of guessing.
- Status: list_builds with a branch or commit filter, get_build for one build, and wait_for_build when the user
  asked you to wait.
- Tests: list_test_runs, get_failed_executions and slowest_executions_for_build.
- Pipelines and agents: list_pipelines, get_pipeline, list_clusters, list_cluster_queues and list_agents.

## Writes need the user's request

create_build, rebuild_build, retry_job, retry_failed_jobs, cancel_build, cancel_job, unblock_job and every
create_ or update_ tool change real CI state. Use one only when the user asked for that action, name the pipeline,
branch and commit first, and report the build URL it returns. If the call fails with a permission error, the token
lacks that scope; say which scope is missing rather than retrying.

## When the server refuses the token

A 401 or "auth required" error means the saved token is missing, expired or revoked. Tell the user to reconnect
Buildkite in Customize → Marketplace. Do not try another endpoint or a different token.
