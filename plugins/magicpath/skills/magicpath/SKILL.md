---
name: magicpath
description: Use MagicPath through the connected magicpath MCP server to find, inspect, install, export, create and edit MagicPath UI components ("designs"). Trigger when the user mentions MagicPath, a MagicPath design, component, project, canvas or generated name like wispy-river-5234; asks to install or export a MagicPath design into local code with 1:1 fidelity; or asks to build or change a component on their MagicPath canvas.
---

# MagicPath

MagicPath is a canvas for building UI components with AI. Users call its components "designs". Each component has a
numeric id, a generated name such as `wispy-river-5234`, and revisions; components live in personal or team projects.

Work through the `magicpath` MCP server's tools. They run the pinned magicpath-ai CLI on this machine with the owner's
MagicPath session, so never run `npx magicpath-ai` or `magicpath-ai login` yourself, and never ask for or print a
token. If a tool reports that MagicPath is not connected or rejected the saved credentials, tell the user to connect
MagicPath in Customize → Marketplace and stop.

## Find and read

1. `magicpath_info` shows the account, its teams and its projects.
2. `magicpath_search` matches component names (substring, case-insensitive) across personal and team projects;
   narrow it with `team` or `personal`. `magicpath_list_projects` and `magicpath_list_components` browse by project.
3. `magicpath_inspect` returns a component's files, npm dependencies and import statement. Large components list
   file sizes only; read one file with `file` and page through it with `offset` until `nextOffset` is null.

When a search finds several plausible matches, show the user the names and projects and let them choose.

## Install into this repository

`magicpath_add` writes components as source into `projectDir`, the directory holding the app's `package.json`
(default the workspace root; pass the app's directory in a monorepo). The component goes under `path` (default
`src/components/magicpath`, relative to `projectDir`) and the shared `cn` helper into `src/lib/utils.ts`. Run it with
`dryRun` first when the target already has files. It never runs a package manager: install the `dependenciesToInstall`
it returns with the repository's own package manager, then import the component as the returned import statement
shows. Only `overwrite` when the user asked to replace what is there. Target directories must stay inside the
workspace and hold no symlinks.

## Export an exact revision

`magicpath_code_export` writes the exact editable files of a component (its selected revision, or `revision`) into a
workspace directory. It changes nothing on MagicPath. Use it to take a design outside MagicPath: reproduce it 1:1
first, check the rendered result against the MagicPath preview, and only then make the changes the user asked for.
Keep the repository's existing behavior, data flow and accessibility, and list every intentional difference.

## Create or edit on the canvas

`magicpath_code_start` and `magicpath_code_submit` change the owner's MagicPath canvas, so use them only when the
user asked for canvas work, and never in a test.

1. `magicpath_code_start` with `project` and `name` creates a pending component; with `component` (and optionally
   `revision`) it starts an edit. Pass `width` and `height` for the target device, such as 390 × 844 or 1440 × 900.
   Use one `dir` per component, and start the session before writing any files so the user sees it on the canvas.
2. Edit only `src/App.tsx`, `src/index.css`, files under `src/components/generated/`, and temporary images under
   `assets/`. `App.tsx` is already wired to the generated component; change it only to switch the theme. Keep
   `@import 'tailwindcss';` and the template's `@theme inline`, `:root` and `.dark` blocks in `src/index.css`, append
   custom CSS below them, and never use `@tailwind` directives. Deleting a file in edit mode deletes it on submit.
3. Build a real, interactive React component: controlled inputs, working handlers, hover, focus and disabled states,
   responsive layout without device mockups, one screen per component (use state for multi-view flows).
4. `magicpath_code_submit` sends the changed files and returns the build job at once. Follow it with
   `magicpath_code_status` until it finishes. If the build fails, fix the files and submit again. If it reports a stale
   base or conflict, start the session again and reapply the edits. Never resubmit when a submission's outcome is
   unknown; check the job with `magicpath_code_status` first.

MagicPath's own agent guide, which this skill condenses for Opulent's tools, is
https://github.com/MagicPathAI/agent-skills/tree/a1ced96ad9da6c65d9f57d9fef79d944f7192dfe/skills/magicpath.
