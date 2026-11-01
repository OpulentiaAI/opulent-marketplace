---
name: depot-builds
description: List Depot projects and container builds and run Depot container builds with the pinned Depot CLI. Use when the user asks about Depot projects, build history, a container build's result, or wants to build an image on Depot.
---

# Depot container builds

DEPOT_TOKEN comes from the Depot plugin's saved secret; see the depot-ci skill for how to run the pinned CLI
(npx -y @depot/cli@0.0.1-cli.2.103.6, written "depot" below) and what to do when the token is refused.

## Read

- depot projects list --output json lists the organization's projects. The plugin's connection check runs exactly
  this command.
- depot list builds --project <project-id> lists a project's builds. depot.json in a repository names its project.
- depot jobs and depot list jobs show GitHub Actions jobs that ran on Depot runners.

## Build

depot build --project <project-id> -t <tag> . builds on Depot's builders with the project's cache, and depot bake
builds from a bake file. Add --push only when the user asked for a push, and name the registry and tag first.
depot build --load pulls the result into the local Docker daemon, so check that one is running before you use it.
Registry credentials are the user's own. Never write one into a command line or a file.
