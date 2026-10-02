#!/usr/bin/env python3
"""Validate generated packages without installing or contacting Mem."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_APP_ID = "asdk_app_REPLACE_WITH_REGISTERED_APP_ID"
APP_ID_RE = re.compile(r"asdk_app_[a-f0-9]{32}\Z")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def contained(root: Path, relative: str, *, file: bool = False) -> Path:
    if not isinstance(relative, str):
        raise ValueError("A file reference is not text.")
    raw = PurePosixPath(relative)
    if raw.is_absolute() or ".." in raw.parts or "\\" in relative:
        raise ValueError("A file reference escapes its package.")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()) or not result.exists():
        raise ValueError("A file reference is outside its package or is missing.")
    if file and not result.is_file():
        raise ValueError("A file reference does not point to a file.")
    return result


def validate(output: Path, *, allow_template: bool = False) -> dict:
    output = output.resolve()
    receipt = read_json(output / "build-receipt.json")
    lock = read_json(ROOT / "upstream.lock.json")
    personal = read_json(ROOT / "personal.json")
    if receipt.get("schema_version") != 1 or receipt.get("personal") != personal:
        raise ValueError("The build receipt schema or personal metadata is invalid.")
    for path in output.rglob("*"):
        if path.is_symlink():
            raise ValueError("Generated packages must not contain links.")
    expected = receipt.get("files", {})
    actual = {
        p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*")) if p.is_file() and p.name != "build-receipt.json"
    }
    if expected != actual:
        raise ValueError("Generated files do not match the build receipt.")
    for reference in expected:
        contained(output, reference, file=True)
    provenance = receipt.get("upstream", {})
    for kind in ["local", "cloud"]:
        package = output / kind
        source = read_json(package / "upstream-provenance.json")
        wanted = {
            "repository": lock["repository"], "commit": lock["commit"],
            "path": lock["packages"][kind]["path"], "version": lock["packages"][kind]["version"],
            "adapter_version": personal["version"],
        }
        if source != wanted or provenance.get(kind) != wanted:
            raise ValueError("The package source differs from the lock file.")
        original = read_json(package / "UPSTREAM-MANIFEST.json")
        if original.get("version") != source["version"]:
            raise ValueError("The original manifest version is inconsistent.")
        manifest = read_json(package / ".codex-plugin" / "plugin.json")
        if manifest.get("name") != personal[kind + "_name"] or manifest.get("version") != personal["version"]:
            raise ValueError("The personal manifest name or version is invalid.")
        skills = contained(package, manifest.get("skills", ""))
        if not skills.is_dir() or not (skills / "nmem-maintenance" / "SKILL.md").is_file():
            raise ValueError("The shared maintenance skill is missing.")
        for field in ["hooks", "apps", "mcpServers"]:
            if field in manifest:
                contained(package, manifest[field], file=True)
        for skill in skills.rglob("SKILL.md"):
            text = skill.read_text(encoding="utf-8")
            if not text.startswith("---\n") or not re.search(r"(?m)^name: .+", text):
                raise ValueError("A skill has no valid name header.")
            for reference in re.findall(r"\]\(([^\s)]+)\)", text):
                if "://" in reference or reference.startswith(("#", "mailto:")):
                    continue
                reference = reference.split("#", 1)[0]
                # Permit links between skills while keeping every link inside the package.
                target = (skill.parent / reference).resolve()
                if not target.is_relative_to(package.resolve()) or not target.exists():
                    raise ValueError("A skill link is outside its package or is missing.")
    if provenance["local"]["commit"] != provenance["cloud"]["commit"]:
        raise ValueError("The two packages use different source commits.")
    local = output / "local"
    local_manifest = read_json(local / ".codex-plugin" / "plugin.json")
    if "apps" in local_manifest:
        raise ValueError("The local package must not add another App connection.")
    mcp = read_json(contained(local, local_manifest["mcpServers"], file=True))
    servers = mcp.get("mcpServers", {})
    if set(servers) != {"nowledge-mem"}:
        raise ValueError("Keep the existing nowledge-mem MCP override key.")
    server = servers["nowledge-mem"]
    if server.get("url") != "http://127.0.0.1:14242/mcp" or server.get("http_headers") != {"APP": "Codex"}:
        raise ValueError("The public local MCP fallback contains private or unexpected settings.")
    hook_doc = read_json(contained(local, local_manifest["hooks"], file=True))
    if set(hook_doc.get("hooks", {})) != {"SessionStart", "SubagentStart", "UserPromptSubmit", "Stop"}:
        raise ValueError("The local lifecycle hook contract changed.")
    for groups in hook_doc["hooks"].values():
        for group in groups:
            for hook in group.get("hooks", []):
                if "PLUGIN_ROOT" not in hook.get("command", ""):
                    raise ValueError("A hook does not use the package root.")
    installer = (local / "scripts" / "install_hooks.py").read_text(encoding="utf-8")
    hook_prefix = personal["local_name"] + "@" + personal["marketplace"] + ":hooks/hooks.json:"
    if hook_prefix not in installer or "nowledge-mem@nowledge-community:hooks" in installer or "nowledge-mem@local:hooks" in installer:
        raise ValueError("The installer hook IDs were not adapted.")
    cloud = output / "cloud"
    cloud_manifest = read_json(cloud / ".codex-plugin" / "plugin.json")
    if "hooks" in cloud_manifest or "mcpServers" in cloud_manifest or (cloud / "hooks").exists() or (cloud / ".mcp.json").exists():
        raise ValueError("The cloud package must use an App without hooks or direct MCP settings.")
    app = read_json(contained(cloud, cloud_manifest["apps"], file=True))
    if set(app) != {"apps"} or set(app["apps"]) != {"nowledge-mem"}:
        raise ValueError("The cloud package must have one Nowledge Mem App reference.")
    app_id = app["apps"]["nowledge-mem"].get("id")
    state = "template" if app_id == TEMPLATE_APP_ID else "bound"
    if state == "template":
        if not allow_template:
            raise ValueError("This is an unbound template. Use --allow-template for template validation.")
    elif not isinstance(app_id, str) or not APP_ID_RE.fullmatch(app_id):
        raise ValueError("The cloud App ID is not a registered ID format.")
    elif not output.is_relative_to((ROOT / ".private").resolve()):
        raise ValueError("A bound package must stay in ignored .private/ output.")
    if receipt.get("cloud_binding") != {"state": state, "app_id": app_id}:
        raise ValueError("The cloud binding does not match the receipt.")
    cloud_skill = (cloud / "skills" / "nowledge-mem" / "SKILL.md").read_text(encoding="utf-8")
    if any(value in cloud_skill for value in ["cloud.nowledge.co", "references the production MCP App", "Nowledge Mem Cloud", "`mem:write`"]):
        raise ValueError("The cloud skill still assumes the publisher's hosted service.")
    return {"source_commit": lock["commit"], "cloud_binding": state, "files_checked": len(actual)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow-template", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(args.output, allow_template=args.allow_template)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Validation failed: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
