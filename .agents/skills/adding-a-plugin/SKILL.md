# Adding a plugin

The repo is itself an Opulent plugin: `.opulent-plugin/plugin.json` lists every
offering under `optionalPlugins`, and that file plus the catalog generated from it
are the only things consumers read. There are two kinds of entry:
`"./plugins/<slug>"` for a plugin authored here (every MCP server Opulent hosts has
one), and a `{ "source", "url", ["path",] "sha" }` object for a third-party plugin
pinned to an exact commit. Entries are sorted and each identity appears once.
`python3 scripts/validate.py` enforces all of this, and CI runs it.

Opulent still reads the Devin layout: a plugin whose manifest is
`.devin-plugin/plugin.json` is accepted when it has no `.opulent-plugin/plugin.json`,
and the same goes for the root manifest. New plugins use `.opulent-plugin`. A plugin
must not have both.

## An MCP server we host

1. Create `plugins/<slug>/.opulent-plugin/plugin.json`, where `<slug>` is the
   marketplace server slug:
   * `name` is the slug. `displayName` is the human title (e.g. `"MySQL"`).
     `description`, `homepage`, `repository` and `keywords` describe the
     server, and the first keyword is the category Opulent shows.
   * Check the brand mark in as `plugins/<slug>/logo.svg` (or `.png`/`.jpg`/`.webp`,
     at most 256 KiB) and set `"logo": "logo.svg"`, a path relative to the plugin
     directory. Opulent serves it from its own origin, so cards never load images
     from a third-party host.
   * `mcpServers` declares exactly one server, keyed by the slug: `command` +
     `args` + `env` for stdio, or `url` (+ `headers`) for HTTP. A stdio
     server is installed and started on the Opulent machine of each run that
     uses the plugin, so its command must run on a stock Linux machine (`npx`,
     `uvx` or a binary the command itself fetches).
     Opulent machines block network access a server hasn't declared. List
     the API hosts a stdio server calls in `allowedHosts` (lowercase public
     hostnames, at most 16, `[]` when it needs no network). The package
     registry for `npx`/`uvx` and https hosts in `args` are added for you,
     and the review sheet shows the full list. A server that names no hosts
     and isn't `[]` is refused, and so is one whose hosts depend on a URL
     the user supplies. Pin the package version (`pkg@1.2.3`). An unpinned
     or `@latest` package installs, but the review sheet warns that it runs
     whatever version is published.
   * Never check in a credential. Anything a user supplies is a plain
     `${<NAME>}` placeholder, resolved from the credentials saved on the
     user's installation (no `MCP_` prefix). When a user installs the plugin,
     Opulent asks for exactly these names in a secure form, or routes into OAuth
     when the server uses it. A stdio `env` value must reference its own key
     (`"AWS_PROFILE": "${AWS_PROFILE}"`) because a saved credential replaces the
     env entry with the same key. In `args` and `headers` the placeholder is the
     credential's only name. `${PLUGIN_ROOT}` is the installed plugin directory.
   * A server can instead run a bridge Opulent's machine image ships. Today that is
     only `opulent-paper-mcp`, which reaches the headless Paper Desktop on desktop
     machines. It takes no `env` credentials. `oauthEnvironment` names the variable
     the owner's OAuth access token fills (`PAPER_MCP_TOKEN`), so installing it
     goes straight into that provider's sign-in.
   * `dependencies` (optional) lists the slugs of other plugins authored here
     that must be installed with this one.
2. Add `"./plugins/<slug>"` to `optionalPlugins` in `.opulent-plugin/plugin.json`.

## A third-party plugin

1. Review the vendor and the exact upstream commit you are endorsing.
2. Add an object to `optionalPlugins`:
   * whole repository: `{ "source": "url", "url": "https://github.com/<owner>/<repo>.git", "sha": "<40-hex>" }`
   * plugin inside a repository: `{ "source": "git-subdir", "url": "...", "path": "<dir>", "sha": "<40-hex>" }`

   Always pin a full 40-hex commit sha, never a branch or tag. Do not add
   display metadata. The plugin's own manifest at that sha supplies it, and
   `--fetch` copies it into the catalog. Nothing else from the upstream repo
   is copied here. If we host the same integration ourselves, author it under
   `plugins/` instead of pointing upstream.

## Both

1. Run `python3 scripts/validate.py --fix` to sort and format the manifest and
   regenerate `catalog.json` and `catalog/bundles/`. Add `--fetch` whenever an
   upstream pin was added or changed: it confirms the pin resolves and records
   its listing. Commit the generated files with the change.
2. To bump an upstream plugin, change its `sha` and run `--fix --fetch`. To
   remove one, delete its entry (and its `plugins/<slug>` directory if it was
   authored here), then run `--fix`.
3. Consumers pin this repo by commit. After the change lands on `main`, bump
   Opulent's pin to the new sha. The pin is `OPULENT_MARKETPLACE_SOURCE` in
   opulentagentasync's `packages/plugin-runtime/src/marketplace.ts`, and a
   deployment can override it with `OPULENT_MARKETPLACE_COMMIT`.
