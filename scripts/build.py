#!/usr/bin/env python3
"""Build personal packages from exact upstream Git objects. No installation."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_APP_ID = "asdk_app_REPLACE_WITH_REGISTERED_APP_ID"
APP_ID_RE = re.compile(r"(?:plugin_)?asdk_app_[a-f0-9]{32}\Z")


def json_read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)


def source_repository(source: Path | None, lock: dict) -> Path:
    repo = source.resolve() if source else ROOT / ".cache" / "upstream"
    if not repo.exists():
        if source:
            raise ValueError("The supplied upstream directory does not exist.")
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout", lock["repository"], str(repo)], check=True)
    origin = git(repo, "remote", "get-url", "origin").decode().strip()
    if origin.removesuffix(".git").rstrip("/") != lock["repository"].removesuffix(".git").rstrip("/"):
        raise ValueError("The upstream origin does not match upstream.lock.json.")
    try:
        git(repo, "cat-file", "-e", lock["commit"] + "^{commit}")
    except subprocess.CalledProcessError:
        subprocess.run(["git", "-C", str(repo), "fetch", "--depth", "1", "origin", lock["commit"]], check=True)
    actual = git(repo, "rev-parse", lock["commit"] + "^{commit}").decode().strip()
    if actual != lock["commit"]:
        raise ValueError("The source commit differs from the lock file.")
    return repo


def archive_packages(repo: Path, lock: dict, stage: Path) -> None:
    paths = [p["path"] for p in lock["packages"].values()]
    for path in paths:
        p = PurePosixPath(path)
        if p.is_absolute() or ".." in p.parts or str(p) == ".":
            raise ValueError("An upstream package path is not contained in the repository.")
    blob = git(repo, "archive", lock["commit"], *paths)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if not parts or parts[0] not in paths or ".." in parts or PurePosixPath(member.name).is_absolute():
                raise ValueError("An upstream archive path escapes its package.")
            target = stage / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("An upstream archive file cannot be read.")
                target.write_bytes(stream.read())
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise ValueError("Upstream links and special files need an explicit review.")


def copy_overlay(package: Path, overlay: Path) -> None:
    if not overlay.exists():
        return
    for source in sorted(overlay.rglob("*")):
        if source.is_symlink():
            raise ValueError("Overlay links are not allowed.")
        if source.is_file():
            target = package / source.relative_to(overlay)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)


def patch_text(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise ValueError(f"Upstream adapter anchor changed: {path.name}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def package_manifest(package: Path, kind: str, personal: dict) -> dict:
    path = package / ".codex-plugin" / "plugin.json"
    original = json_read(path)
    json_write(package / "UPSTREAM-MANIFEST.json", original)
    manifest = dict(original)
    manifest["name"] = personal[kind + "_name"]
    manifest["version"] = personal["version"]
    manifest["author"] = {"name": personal["developer_name"]}
    manifest["description"] = "Use Nowledge Mem with portable memory workflows and EVOLVES-first knowledge maintenance."
    manifest["interface"] = dict(original.get("interface", {}))
    manifest["interface"].update({
        "displayName": personal["display_name"] + (" Local" if kind == "local" else " Remote"),
        "developerName": personal["developer_name"],
        "shortDescription": "Memory workflows and knowledge maintenance",
    })
    manifest["interface"]["longDescription"] = (
        "Use the local Codex connector and lifecycle hooks."
        if kind == "local" else "Use an existing remote Nowledge Mem App connection. This package does not capture transcripts."
    )
    json_write(path, manifest)
    return original


def adapt_local(package: Path, personal: dict) -> None:
    # The publisher's fixture tests are source material, not runtime package assets.
    tests = package / "tests"
    if tests.exists():
        shutil.rmtree(tests)
    installer = package / "scripts" / "install_hooks.py"
    target = personal["local_name"] + "@" + personal["marketplace"]
    patch_text(installer, "nowledge-mem@nowledge-community", target)
    patch_text(installer, "nowledge-mem@local", target)
    validator = package / "scripts" / "validate-plugin.mjs"
    patch_text(validator, 'manifest.name !== "nowledge-mem"', 'manifest.name !== ' + json.dumps(personal["local_name"]))
    changelog = package / "CHANGELOG.md"
    changelog.write_text(
        "# Personal adapter changes\n\n## [" + personal["version"] + "]\n\n"
        "Add the portable maintenance skill and personal package metadata. Keep the upstream MCP key and hook layout.\n\n"
        + changelog.read_text(encoding="utf-8"), encoding="utf-8",
    )


def adapt_cloud(package: Path, app_id: str) -> None:
    json_write(package / ".app.json", {"apps": {"nowledge-mem": {"id": app_id}}})
    skill = package / "skills" / "nowledge-mem" / "SKILL.md"
    patch_text(skill, "Nowledge Mem Cloud", "Nowledge Mem")
    patch_text(skill,
        "If the Nowledge Mem tools are unavailable, direct the user to the official setup guide at `https://mem.nowledge.co/docs/integrations/chatgpt-web`. The MCP endpoint must be public HTTPS and end in `/mcp`. Complete the host's OAuth flow; never ask the user to paste a Nowledge API key into chat.",
        "Use the existing Nowledge Mem App connection. It can point to a self-hosted server or a hosted workspace. If its tools are unavailable, check that connection in the host settings. Follow its actual authentication flow; never ask the user to paste an API key into chat.")
    patch_text(skill,
        "This public plugin package references the production MCP App registered with OpenAI. The bundled skill guides usage after the host establishes that per-user OAuth connection; installing the skill alone does not authorize or expose a Cloud workspace.",
        "This personal package uses the App reference supplied at build time. The public template has no active binding. The skill alone does not authorize or expose a workspace. Do not create another App when an existing registered connection is available.")
    patch_text(skill, "A write may require separately approved `mem:write` scope.",
        "Use the permissions and scopes of the actual connection. Request any required write permission through the host.")
    # These files provision and test the publisher's official Cloud App. They are not personal runtime files.
    for relative in ["SUBMISSION.md", "scripts", "tests"]:
        target = package / relative
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def content_hashes(output: Path) -> dict[str, str]:
    return {
        p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*")) if p.is_file() and p.name != "build-receipt.json"
    }


def build(*, upstream_dir: Path | None = None, output_dir: Path | None = None, app_id: str | None = None) -> Path:
    lock = json_read(ROOT / "upstream.lock.json")
    personal = json_read(ROOT / "personal.json")
    if not re.fullmatch(r"[a-f0-9]{40}", lock["commit"]):
        raise ValueError("The upstream lock must contain a full Git commit.")
    if app_id is not None and not APP_ID_RE.fullmatch(app_id):
        raise ValueError("Use an actual registered asdk_app_ or plugin_asdk_app_ ID.")
    if app_id is not None:
        # The App reference uses an App ID, not its enclosing plugin identity.
        app_id = app_id.removeprefix("plugin_")
    output = (output_dir or ROOT / (".private/dist" if app_id else "dist")).resolve()
    if app_id and not output.is_relative_to((ROOT / ".private").resolve()):
        raise ValueError("A bound package must be built inside ignored .private/ output.")
    if ROOT.is_relative_to(output):
        raise ValueError("The output must not contain the source repository.")
    for reserved in [ROOT, ROOT / "scripts", ROOT / "overlay", ROOT / "upstream", ROOT / ".cache", ROOT / ".git"]:
        if output == reserved.resolve() or output.is_relative_to(reserved.resolve()) and reserved != ROOT:
            raise ValueError("The output overlaps source or repository state.")
    if output.exists() and any(output.iterdir()) and not (output / "build-receipt.json").is_file():
        raise ValueError("Refuse to replace an output directory that has no build receipt.")
    overlay = ROOT / "overlay" / "common" / "skills" / "nmem-maintenance"
    if not (overlay / "SKILL.md").is_file():
        raise ValueError("The shared maintenance overlay is missing.")
    repo = source_repository(upstream_dir, lock)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".nmem-build-", dir=output.parent) as temporary:
        workspace = Path(temporary)
        extracted = workspace / "source"
        final = workspace / "output"
        final.mkdir()
        archive_packages(repo, lock, extracted)
        provenance = {}
        for kind in ["local", "cloud"]:
            source = extracted / lock["packages"][kind]["path"]
            package = final / kind
            shutil.copytree(source, package)
            original = package_manifest(package, kind, personal)
            if original["version"] != lock["packages"][kind]["version"]:
                raise ValueError("The upstream package version differs from the lock file.")
            if kind == "local":
                adapt_local(package, personal)
            else:
                adapt_cloud(package, app_id or TEMPLATE_APP_ID)
            copy_overlay(package, ROOT / "overlay" / "common")
            copy_overlay(package, ROOT / "overlay" / kind)
            for name in ["NOTICE.md", "LICENSE"]:
                if (ROOT / name).is_file():
                    shutil.copyfile(ROOT / name, package / (name if name == "NOTICE.md" else "PERSONAL-LICENSE"))
            provenance[kind] = {
                "repository": lock["repository"], "commit": lock["commit"],
                "path": lock["packages"][kind]["path"], "version": original["version"],
                "adapter_version": personal["version"],
            }
            json_write(package / "upstream-provenance.json", provenance[kind])
            (package / "README.md").write_text(
                "# " + personal["display_name"] + "\n\n"
                "This is a personal adapter of the Nowledge Labs community package.\n"
                "See UPSTREAM-MANIFEST.json and upstream-provenance.json for source details.\n\n"
                + ("Use one local lifecycle hook set. Review new hooks before use. Keep server credentials in private client settings.\n"
                   if kind == "local" else "This package uses an existing remote App. The public template is unbound. Build a private bound package before use. Remote MCP does not capture host transcripts.\n"),
                encoding="utf-8",
            )
        integrations = json.loads(git(repo, "show", lock["commit"] + ":integrations.json"))
        for item in integrations["integrations"]:
            if item["id"] == "codex-cli":
                item["version"] = personal["version"]
        json_write(final / "integrations.json", integrations)
        receipt = {
            "schema_version": 1, "upstream": provenance,
            "personal": personal,
            "cloud_binding": {"state": "bound" if app_id else "template", "app_id": app_id or TEMPLATE_APP_ID},
            "files": content_hashes(final),
        }
        json_write(final / "build-receipt.json", receipt)
        if output.exists():
            shutil.rmtree(output)
        shutil.move(str(final), output)
    if output == (ROOT / "packages").resolve():
        json_write(ROOT / ".agents" / "plugins" / "marketplace.json", {
            "name": personal["marketplace"],
            "interface": {"displayName": personal["display_name"]},
            "plugins": [{"name": personal["local_name"], "source": {"source": "local", "path": "./packages/local"}, "category": "Productivity"}],
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--app-id", help="Registered App ID; bound output is restricted to .private/.")
    args = parser.parse_args()
    try:
        output = build(upstream_dir=args.upstream_dir, output_dir=args.output_dir, app_id=args.app_id)
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError) as error:
        # Git stderr may contain authenticated remote URLs. Do not echo command/error details.
        if isinstance(error, subprocess.CalledProcessError):
            parser.exit(1, "Build failed: an upstream Git operation failed.\n")
        parser.exit(1, f"Build failed: {error}\n")
    print(f"Built packages in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
