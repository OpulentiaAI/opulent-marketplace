# Opulent marketplace

The plugins Opulent's marketplace offers: one plugin for every MCP server Opulent hosts, plus third-party plugins
pinned to reviewed commits.

## Using a plugin

In Opulent, open Customize → Plugins, pick a plugin, and install it. Opulent asks for any credentials or OAuth
authorization the plugin's server needs while you install it. Nothing in this repo holds a credential.

You can also reference a plugin from your own plugin manifest, pinned to a commit of this repo:

```json
{
  "requiredPlugins": [
    {
      "source": "git-subdir",
      "url": "https://github.com/OpulentiaAI/devin-marketplace.git",
      "path": "plugins/notion",
      "sha": "<commit>"
    }
  ]
}
```

## How Opulent reads this repo

Opulent pins this repo by commit and reads `catalog.json` once to list every plugin. It then reads one
`catalog/bundles/<slug>.json` to preview and install a plugin. `scripts/validate.py --fix` generates both from the
manifests, and CI fails when they are stale, so never edit them by hand. Each listing carries
`legacyIdentities` that name the plugin's identity in the Devin marketplace this repo was forked from, so
existing installs can be upgraded to it.

The repo is staged on GitHub now and moves to Entire at launch. The commit pin stays the same, and only the
remote Opulent reads it from changes.

## Contributing

See [`.agents/skills/adding-a-plugin/SKILL.md`](.agents/skills/adding-a-plugin/SKILL.md).

## License

[MIT](LICENSE). This repo is forked from
[CognitionAI/devin-marketplace](https://github.com/CognitionAI/devin-marketplace) at
`d9f808ca5095ce3069400f494f9b533060b2b47d`, and its history and copyright notice are kept. Third-party plugins
listed by pin are not copied here, and each one keeps its upstream license.
