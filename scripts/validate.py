#!/usr/bin/env python3
"""Validate the Opulent marketplace and keep its catalog current.

    python3 scripts/validate.py          # structural checks; fails when catalog.json is stale
    python3 scripts/validate.py --fix    # also rewrite plugin.json in canonical form and regenerate the catalog
    python3 scripts/validate.py --fetch  # also confirm every pinned sha exists upstream and refresh its listing

The root manifest (.opulent-plugin/plugin.json) lists every offering under optionalPlugins. Plugins authored here
live in plugins/<slug>/ with a .opulent-plugin/plugin.json manifest; a .devin-plugin/plugin.json manifest is still
read when a plugin has no Opulent one. catalog.json and catalog/bundles/ are generated from those manifests: Opulent
reads catalog.json once to list the marketplace and one bundle to preview a plugin, so never edit them by hand.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIRS = (".opulent-plugin", ".devin-plugin")
UPSTREAM_MANIFESTS = (".opulent-plugin/plugin.json", ".devin-plugin/plugin.json", ".claude-plugin/plugin.json", "plugin.json")
PLUGINS = ROOT / "plugins"
CATALOG = ROOT / "catalog.json"
BUNDLES = ROOT / "catalog" / "bundles"
CATALOG_SCHEMA = 1
LEGACY_REPOSITORY = "github.com/cognitionai/devin-marketplace"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
NAME_RE = re.compile(r"^[a-z0-9]+([.-][a-z0-9]+)*$")
URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9._-]{0,99}\.git$")
LOCAL_RE = re.compile(r"^\./plugins/([a-z0-9]+([.-][a-z0-9]+)*)$")
PLACEHOLDER_RE = re.compile(r"\$\{([^}]*)\}")
CREDENTIAL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RUNTIME_PLACEHOLDERS = {"CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT"}
LOGO_RE = re.compile(r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*\.(svg|png|jpg|jpeg|webp)$")
LOGO_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
RASTER_RE = re.compile(r"\.(png|jpe?g|gif|webp|ico)$", re.IGNORECASE)
MAX_LOGO_BYTES = 256 * 1024
TOP_LEVEL_KEYS = {"name", "displayName", "description", "homepage", "repository", "skills", "optionalPlugins"}
UPSTREAM_KEYS = {"source", "url", "path", "sha"}
PLUGIN_KEYS = {
    "name",
    "displayName",
    "description",
    "homepage",
    "repository",
    "logo",
    "keywords",
    "dependencies",
    "mcpServers",
}
STDIO_KEYS = {"command", "args", "env", "allowedHosts"}
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
PRIVATE_SUFFIXES = (".local", ".internal", ".localhost")
MAX_ALLOWED_HOSTS = 16
HTTP_KEYS = {"url", "headers", "transport", "oauthClientId", "oauthScopes"}


def identity(plugin: object) -> tuple[str, str]:
    if isinstance(plugin, str):
        return (plugin, "")
    return (plugin["url"], plugin.get("path", ""))


def manifest_path(directory: Path) -> Path | None:
    for name in MANIFEST_DIRS:
        candidate = directory / name / "plugin.json"
        if candidate.is_file():
            return candidate
    return None


def check_upstream(where: str, plugin: dict, errors: list[str]) -> None:
    extra = set(plugin) - UPSTREAM_KEYS
    if extra:
        errors.append(f"{where}: unexpected keys {sorted(extra)}")
    kind = plugin.get("source")
    if kind not in ("url", "git-subdir"):
        errors.append(f"{where}: source must be 'url' or 'git-subdir'")
    url = plugin.get("url")
    if not isinstance(url, str) or not URL_RE.match(url):
        errors.append(f"{where}: url must be a GitHub repository URL ending in .git; Opulent reads upstream plugins from GitHub")
    sha = plugin.get("sha")
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        errors.append(f"{where}: sha must be a full 40-character lowercase commit sha")
    path = plugin.get("path")
    if kind == "git-subdir":
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/"):
            errors.append(f"{where}: git-subdir needs a relative 'path' inside the repository")
    elif path is not None:
        errors.append(f"{where}: 'path' is only valid for git-subdir sources")


def check_entry(index: int, plugin: object, errors: list[str]) -> None:
    where = f"optionalPlugins[{index}]"
    if isinstance(plugin, str):
        match = LOCAL_RE.match(plugin)
        if not match:
            errors.append(f"{where}: a local reference must look like './plugins/<slug>'")
        elif manifest_path(PLUGINS / match.group(1)) is None:
            errors.append(f"{where}: {plugin} has no .opulent-plugin/plugin.json")
        return
    if isinstance(plugin, dict):
        check_upstream(where, plugin, errors)
        return
    errors.append(f"{where}: must be a './plugins/<slug>' string or a pinned upstream object")


def placeholder_name(reference: str) -> str:
    # ${NAME:-default} falls back to default when NAME has no saved value.
    return reference.split(":-", 1)[0]


def check_placeholders(where: str, value: str, errors: list[str]) -> None:
    for reference in PLACEHOLDER_RE.findall(value):
        name = placeholder_name(reference)
        if name in RUNTIME_PLACEHOLDERS:
            continue
        if not CREDENTIAL_NAME_RE.match(name):
            errors.append(f"{where}: placeholder ${{{name}}} is not a credential name the runtime can resolve")
        elif name.startswith("MCP_"):
            errors.append(f"{where}: placeholder ${{{name}}} uses the retired MCP_ prefix; name the credential ${{{name[4:]}}}")


def check_env_placeholders(where: str, env: dict[str, object], errors: list[str]) -> None:
    for key, value in env.items():
        if not isinstance(value, str):
            continue
        for reference in PLACEHOLDER_RE.findall(value):
            name = placeholder_name(reference)
            if name not in RUNTIME_PLACEHOLDERS and name != key:
                errors.append(f"{where}: env {key} references ${{{name}}}; a saved credential is matched by the env key, so it must be ${{{key}}}")


def check_server(where: str, slug: str, config: object, errors: list[str]) -> None:
    if not isinstance(config, dict):
        errors.append(f"{where}: server '{slug}' must be an object")
        return
    stdio = "command" in config
    allowed = STDIO_KEYS if stdio else HTTP_KEYS
    extra = set(config) - allowed - {"description"}
    if extra:
        errors.append(f"{where}: server '{slug}' has unexpected keys {sorted(extra)}")
    if stdio:
        args = config.get("args", [])
        env = config.get("env", {})
        if not isinstance(args, list):
            errors.append(f"{where}: server '{slug}' args must be a list")
            return
        if not isinstance(env, dict):
            errors.append(f"{where}: server '{slug}' env must be an object")
            return
        hosts = config.get("allowedHosts", [])
        if (
            not isinstance(hosts, list)
            or len(hosts) > MAX_ALLOWED_HOSTS
            or any(not isinstance(host, str) or not HOST_RE.match(host) or host.endswith(PRIVATE_SUFFIXES) for host in hosts)
        ):
            errors.append(f"{where}: server '{slug}' allowedHosts must list at most {MAX_ALLOWED_HOSTS} lowercase public hostnames")
        strings = [config["command"], *args, *env.values()]
        check_env_placeholders(f"{where} ({slug})", env, errors)
    else:
        url = config.get("url")
        headers = config.get("headers", {})
        if not isinstance(url, str) or not url.startswith("https://"):
            errors.append(f"{where}: server '{slug}' needs an https url or a command")
            return
        if not isinstance(headers, dict):
            errors.append(f"{where}: server '{slug}' headers must be an object")
            return
        strings = [url, *headers.values()]
    for value in strings:
        if not isinstance(value, str):
            errors.append(f"{where}: server '{slug}' has a non-string value")
            continue
        check_placeholders(f"{where} ({slug})", value, errors)


def check_logo(where: str, slug: str, logo: object, errors: list[str]) -> None:
    if not isinstance(logo, str) or not logo:
        errors.append(f"{where}: logo must be a string")
        return
    if logo.startswith("https://"):
        return
    if not LOGO_RE.match(logo):
        errors.append(f"{where}: logo must be an https url or a plain repo-relative file path")
        return
    path = PLUGINS / slug / logo
    if not path.is_file():
        errors.append(f"{where}: logo '{logo}' does not exist in the plugin directory")
    elif path.stat().st_size > MAX_LOGO_BYTES:
        errors.append(f"{where}: logo '{logo}' is larger than {MAX_LOGO_BYTES // 1024} KiB")


def check_local_plugin(slug: str, local: set[str], errors: list[str]) -> None:
    where = f"plugins/{slug}"
    if all((PLUGINS / slug / name / "plugin.json").is_file() for name in MANIFEST_DIRS):
        errors.append(f"{where}: has both .opulent-plugin and .devin-plugin manifests; keep only .opulent-plugin")
    path = manifest_path(PLUGINS / slug)
    if path is None:
        errors.append(f"{where}: missing .opulent-plugin/plugin.json")
        return
    data = json.loads(path.read_text())
    extra = set(data) - PLUGIN_KEYS
    if extra:
        errors.append(f"{where}: unexpected keys {sorted(extra)}")
    if data.get("name") != slug:
        errors.append(f"{where}: name must match the directory ({slug})")
    display_name = data.get("displayName")
    if display_name is not None and (
        not isinstance(display_name, str)
        or display_name != display_name.strip()
        or not display_name
        or any(ch.isspace() and ch != " " for ch in display_name)
    ):
        errors.append(f"{where}: displayName must be one non-empty line without surrounding whitespace")
    logo = data.get("logo")
    if logo is not None:
        check_logo(where, slug, logo, errors)
    dependencies = data.get("dependencies", [])
    if not isinstance(dependencies, list) or any(not isinstance(item, str) or item == slug or item not in local for item in dependencies):
        errors.append(f"{where}: dependencies must list other plugins authored here by slug")
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or len(servers) != 1 or slug not in servers:
        errors.append(f"{where}: mcpServers must declare exactly one server named '{slug}'")
        return
    check_server(where, slug, servers[slug], errors)


def canonical(data: dict) -> str:
    ordered: list[object] = []
    for plugin in sorted(data["optionalPlugins"], key=identity):
        if isinstance(plugin, str):
            ordered.append(plugin)
            continue
        entry = {"source": plugin["source"], "url": plugin["url"]}
        if "path" in plugin:
            entry["path"] = plugin["path"]
        entry["sha"] = plugin["sha"]
        ordered.append(entry)
    out = {key: data[key] for key in data if key != "optionalPlugins"}
    out["optionalPlugins"] = ordered
    return json.dumps(out, indent=2) + "\n"


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def walk(directory: Path, base: Path) -> list[tuple[str, Path]]:
    # A symlink is listed, never followed: Opulent refuses to install a plugin that contains one.
    found: list[tuple[str, Path]] = []
    for entry in os.scandir(directory):
        path = Path(entry.path)
        if entry.is_dir(follow_symlinks=False):
            found.extend(walk(path, base))
        else:
            found.append((path.relative_to(base).as_posix(), path))
    return found


def text_of(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def category(manifest: dict) -> str:
    keywords = manifest.get("keywords")
    return keywords[0] if isinstance(keywords, list) and keywords and isinstance(keywords[0], str) else "MCP"


def local_listing(slug: str) -> tuple[dict, str]:
    directory = PLUGINS / slug
    manifest_file = manifest_path(directory)
    manifest = json.loads(manifest_file.read_text())
    entries: list[dict] = []
    files: list[dict] = []
    for relative, path in sorted(walk(directory, directory), key=lambda item: item[0].encode("utf-16-be")):
        if path.is_symlink():
            target = os.readlink(path).encode()
            entries.append({"path": relative, "mode": "120000", "bytes": len(target), "sha256": sha256(target), "text": False})
            continue
        data = path.read_bytes()
        mode = "0755" if path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) else "0644"
        content = None if RASTER_RE.search(relative) else text_of(data)
        entries.append({"path": relative, "mode": mode, "bytes": len(data), "sha256": sha256(data), "text": content is not None})
        if content is not None:
            files.append({"path": relative, "mode": mode, "content": content})
    content_hash = "sha256:" + sha256(compact([[entry["path"], entry["mode"], entry["sha256"]] for entry in entries]).encode())
    listing: dict = {"name": slug}
    if manifest.get("displayName"):
        listing["displayName"] = manifest["displayName"]
    listing["description"] = manifest.get("description", "")
    listing["category"] = category(manifest)
    listing["keywords"] = [keyword for keyword in manifest.get("keywords", []) if isinstance(keyword, str)]
    listing["path"] = f"plugins/{slug}"
    listing["manifestPath"] = manifest_file.relative_to(directory).as_posix()
    if manifest.get("homepage"):
        listing["homepage"] = manifest["homepage"]
    listing["dependencies"] = [{"name": name, "ref": None} for name in manifest.get("dependencies", [])]
    listing["mcpServers"] = sorted(manifest.get("mcpServers", {}))
    logo = manifest.get("logo")
    logo_entry = next((entry for entry in entries if isinstance(logo, str) and entry["path"] == logo), None)
    if logo_entry is not None and logo_entry["bytes"] <= MAX_LOGO_BYTES and Path(logo).suffix.lower() in LOGO_TYPES:
        listing["logo"] = {"path": logo, "mediaType": LOGO_TYPES[Path(logo).suffix.lower()], "bytes": logo_entry["bytes"], "sha256": logo_entry["sha256"]}
    listing["fileCount"] = len(entries)
    listing["bytes"] = sum(entry["bytes"] for entry in entries)
    listing["contentHash"] = content_hash
    listing["bundle"] = f"catalog/bundles/{slug}.json"
    listing["legacyIdentities"] = [f"{LEGACY_REPOSITORY}/plugins/{slug}"]
    bundle = compact({"schema": CATALOG_SCHEMA, "name": slug, "contentHash": content_hash, "entries": entries, "files": files}) + "\n"
    return listing, bundle


def upstream_pin(plugin: dict) -> dict:
    return {"url": plugin["url"], "path": plugin.get("path", ""), "sha": plugin["sha"]}


def fetch_upstream(plugin: dict) -> dict | None:
    """Clones the pinned commit and reads the plugin's own manifest; None when the sha does not resolve."""
    with tempfile.TemporaryDirectory() as tmp:
        for cmd in (["git", "init", "-q"], ["git", "fetch", "-q", "--depth", "1", plugin["url"], plugin["sha"]], ["git", "checkout", "-q", "FETCH_HEAD"]):
            if subprocess.run(cmd, cwd=tmp, capture_output=True).returncode != 0:
                return None
        directory = Path(tmp) / plugin.get("path", "")
        found = next((name for name in UPSTREAM_MANIFESTS if (directory / name).is_file()), None)
        manifest = json.loads((directory / found).read_text()) if found else {}
        name = manifest.get("name") or Path(plugin.get("path") or plugin["url"].removesuffix(".git")).name
        listing: dict = {"name": name}
        if manifest.get("displayName"):
            listing["displayName"] = manifest["displayName"]
        listing["description"] = manifest.get("description", "")
        listing["category"] = category(manifest)
        listing["keywords"] = [keyword for keyword in manifest.get("keywords", []) if isinstance(keyword, str)]
        listing["manifestPath"] = found or "plugin.json"
        if manifest.get("homepage"):
            listing["homepage"] = manifest["homepage"]
        listing["dependencies"] = []
        servers = manifest.get("mcpServers")
        listing["mcpServers"] = sorted(servers) if isinstance(servers, dict) else []
        listing["upstream"] = upstream_pin(plugin)
        listing["legacyIdentities"] = []
        return listing


def build_catalog(data: dict, fetched: dict[tuple[str, str], dict], errors: list[str]) -> dict[Path, str]:
    previous = json.loads(CATALOG.read_text()).get("plugins", []) if CATALOG.is_file() else []
    listings: list[dict] = []
    outputs: dict[Path, str] = {}
    for plugin in data["optionalPlugins"]:
        if isinstance(plugin, str):
            slug = LOCAL_RE.match(plugin).group(1)
            listing, bundle = local_listing(slug)
            outputs[BUNDLES / f"{slug}.json"] = bundle
            listings.append(listing)
            continue
        listing = fetched.get(identity(plugin)) or next((item for item in previous if item.get("upstream") == upstream_pin(plugin)), None)
        if listing is None:
            errors.append(f"{plugin['url']}: no catalog listing for sha {plugin['sha']}; run scripts/validate.py --fix --fetch")
            continue
        listings.append(listing)
    names = [listing["name"] for listing in listings]
    for name in sorted({name for name in names if names.count(name) > 1}):
        errors.append(f"catalog: plugin name '{name}' is listed more than once")
    catalog = {
        "schema": CATALOG_SCHEMA,
        "name": data["name"],
        "displayName": data.get("displayName", data["name"]),
        "description": data.get("description", ""),
        "plugins": listings,
    }
    outputs[CATALOG] = json.dumps(catalog, ensure_ascii=False, indent=1) + "\n"
    return outputs


def stale_outputs(outputs: dict[Path, str]) -> list[str]:
    stale = [path for path, body in outputs.items() if not path.is_file() or path.read_text() != body]
    extra = [path for path in BUNDLES.glob("*") if path not in outputs] if BUNDLES.is_dir() else []
    return sorted(path.relative_to(ROOT).as_posix() for path in [*stale, *extra])


def write_outputs(outputs: dict[Path, str]) -> None:
    shutil.rmtree(BUNDLES, ignore_errors=True)
    BUNDLES.mkdir(parents=True)
    for path, body in outputs.items():
        path.write_text(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()

    manifest = manifest_path(ROOT)
    if manifest is None:
        print("missing .opulent-plugin/plugin.json")
        return 1
    text = manifest.read_text()
    data = json.loads(text)
    errors: list[str] = []

    if not isinstance(data, dict):
        print("plugin.json: top level must be an object")
        return 1
    extra = set(data) - TOP_LEVEL_KEYS
    if extra:
        errors.append(f"unexpected top-level keys {sorted(extra)}")
    if "requiredPlugins" in data:
        errors.append("marketplace plugins are optional; use optionalPlugins")
    if not isinstance(data.get("name"), str) or not NAME_RE.match(data["name"]):
        errors.append("name must be lowercase alphanumeric with '-' or '.' separators")
    plugins = data.get("optionalPlugins")
    if not isinstance(plugins, list):
        errors.append("optionalPlugins must be a list")
        plugins = []
    for i, plugin in enumerate(plugins):
        check_entry(i, plugin, errors)
    if errors:
        print("\n".join(errors))
        return 1

    seen: dict[tuple[str, str], int] = {}
    for i, plugin in enumerate(plugins):
        key = identity(plugin)
        if key in seen:
            errors.append(f"optionalPlugins[{i}] duplicates optionalPlugins[{seen[key]}]: {key}")
        seen[key] = i

    listed = {identity(p)[0] for p in plugins if isinstance(p, str)}
    authored = sorted(d.name for d in PLUGINS.iterdir() if d.is_dir()) if PLUGINS.is_dir() else []
    for slug in authored:
        if f"./plugins/{slug}" not in listed:
            errors.append(f"plugins/{slug}: not listed in optionalPlugins")
        check_local_plugin(slug, set(authored), errors)

    want = canonical(data)
    if text != want:
        if args.fix:
            manifest.write_text(want)
            data = json.loads(want)
            print(f"rewrote {manifest.relative_to(ROOT)}")
        else:
            errors.append("plugin.json is not canonical; run scripts/validate.py --fix")

    fetched: dict[tuple[str, str], dict] = {}
    if args.fetch:
        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue
            listing = fetch_upstream(plugin)
            if listing is None:
                errors.append(f"{plugin['url']}: sha {plugin['sha']} not found upstream")
            elif len(listing["name"]) > 64 or not NAME_RE.match(listing["name"]):
                errors.append(f"{plugin['url']}: upstream plugin name '{listing['name']}' is not a lowercase slug Opulent accepts")
            else:
                fetched[identity(plugin)] = listing

    if errors:
        print("\n".join(errors))
        return 1
    outputs = build_catalog(data, fetched, errors)
    stale = [] if errors else stale_outputs(outputs)
    if stale and args.fix:
        write_outputs(outputs)
        print(f"wrote catalog.json and {len(outputs) - 1} bundles")
    elif stale:
        errors.append(f"catalog is stale ({', '.join(stale[:5])}{', ...' if len(stale) > 5 else ''}); run scripts/validate.py --fix")

    if errors:
        print("\n".join(errors))
        return 1
    print(f"ok: {len(plugins)} entries ({len(authored)} authored, {len(plugins) - len(authored)} upstream)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
