#!/usr/bin/env python3
"""Prepare a private cloud update from a downloaded plugin backup. No upload."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import build as package_builder
import validate as package_validator

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".private"
VERSION_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
MANIFEST = ".codex-plugin/plugin.json"


def original_metadata(archive_path: Path) -> tuple[dict, dict, str]:
    """Read only the manifest and its one-App mapping, without extracting files."""
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("The backup has duplicate archive entries.")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("The backup has an unsafe archive path.")
        manifests = [name for name in names if name == MANIFEST or name.endswith("/" + MANIFEST)]
        if len(manifests) != 1:
            raise ValueError("The backup must contain exactly one compatibility plugin manifest.")
        manifest_path = manifests[0]
        prefix = manifest_path.removesuffix(MANIFEST)
        if prefix and (len(PurePosixPath(prefix).parts) != 1 or any(not n.startswith(prefix) for n in names)):
            raise ValueError("The backup must have one plugin root.")

        def read_object(name: str) -> dict:
            if archive.getinfo(name).file_size > 1024 * 1024:
                raise ValueError("Backup metadata exceeds the supported size.")
            value = json.loads(archive.read(name).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Backup metadata must contain JSON objects.")
            return value

        manifest = read_object(manifest_path)
        name = manifest.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
            raise ValueError("The backup has no supported plugin name.")
        if not isinstance(manifest.get("version"), str) or not VERSION_RE.fullmatch(manifest["version"]):
            raise ValueError("The original deployment version must be ordinary x.y.z semver.")
        app_reference = manifest.get("apps")
        if not isinstance(app_reference, str) or app_reference.removeprefix("./") != ".app.json":
            raise ValueError("The backup must reference its root .app.json.")
        if "hooks" in manifest or "mcpServers" in manifest:
            raise ValueError("The backup must be an App-based cloud wrapper without hooks or direct MCP settings.")
        mapping = read_object(prefix + ".app.json")
        apps = mapping.get("apps")
        if set(mapping) != {"apps"} or not isinstance(apps, dict) or len(apps) != 1:
            raise ValueError("The backup must contain exactly one App reference.")
        app = next(iter(apps.values()))
        if not isinstance(app, dict) or set(app) != {"id"}:
            raise ValueError("The backup App reference must contain only its registered ID.")
        app_id = app["id"]
        if not isinstance(app_id, str) or not package_validator.APP_ID_RE.fullmatch(app_id):
            raise ValueError("The backup App reference is not a registered App ID.")
        return manifest, mapping, app_id


def prepare(*, original_zip: Path, output_dir: Path, upstream_dir: Path | None = None) -> dict:
    original_zip = original_zip.resolve()
    output = output_dir.resolve()
    private = PRIVATE.resolve()
    if output == private or not output.is_relative_to(private):
        raise ValueError("The output directory must be inside .private/.")
    if original_zip.is_relative_to(output):
        raise ValueError("The output directory must not contain the original backup.")
    ignored = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--quiet", "--", str(output / "privacy-check")],
        capture_output=True,
    )
    if ignored.returncode != 0:
        raise ValueError("The private output is not ignored by Git.")
    if output.exists() and any(output.iterdir()) and not (output / "preparation-receipt.json").is_file():
        raise ValueError("Refuse to replace an output directory without a preparation receipt.")
    original, mapping, app_id = original_metadata(original_zip)
    version_parts = VERSION_RE.fullmatch(original["version"]).groups()
    deployment_version = ".".join([version_parts[0], version_parts[1], str(int(version_parts[2]) + 1)])
    personal = package_builder.json_read(ROOT / "personal.json")
    lock = package_builder.json_read(ROOT / "upstream.lock.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".nmem-cloud-update-", dir=output.parent) as temporary:
        workspace = Path(temporary)
        base = package_builder.build(upstream_dir=upstream_dir, output_dir=workspace / "base", app_id=app_id)
        checked = package_validator.validate(base)
        result = workspace / "result"
        cloud = result / "cloud"
        shutil.copytree(base / "cloud", cloud)
        manifest_path = cloud / MANIFEST
        manifest = package_builder.json_read(manifest_path)
        skills_reference = manifest["skills"]
        manifest["name"] = original["name"]
        manifest["version"] = deployment_version
        manifest["interface"]["displayName"] = personal["display_name"]
        package_builder.json_write(manifest_path, manifest)
        package_builder.json_write(cloud / ".app.json", mapping)
        provenance = package_builder.json_read(cloud / "upstream-provenance.json")
        if (manifest["name"] != original["name"] or manifest["skills"] != skills_reference
                or package_builder.json_read(cloud / ".app.json") != mapping
                or provenance["adapter_version"] != personal["version"]
                or provenance["commit"] != lock["commit"]
                or "hooks" in manifest or "mcpServers" in manifest):
            raise ValueError("The private deployment metadata failed its consistency check.")
        deployment = {
            "schema_version": 1,
            "previous_deployment_version": original["version"],
            "deployment_version": deployment_version,
            "adapter_version": personal["version"],
            "source_commit": lock["commit"],
            "original_archive_sha256": hashlib.sha256(original_zip.read_bytes()).hexdigest(),
        }
        package_builder.json_write(cloud / "deployment-provenance.json", deployment)
        zip_name = "nowledge-mem-personal-cloud-update-" + deployment_version + ".zip"
        zip_path = result / zip_name
        files = [p for p in sorted(cloud.rglob("*")) if p.is_file()]
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(cloud).as_posix())
        with zipfile.ZipFile(zip_path) as archive:
            if archive.testzip() is not None or set(archive.namelist()) != {p.relative_to(cloud).as_posix() for p in files}:
                raise ValueError("The generated deployment ZIP failed its integrity check.")
        package_builder.json_write(result / "preparation-receipt.json", {
            **deployment,
            "files": package_builder.content_hashes(cloud),
            "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        })
        if output.exists():
            shutil.rmtree(output)
        shutil.move(str(result), output)
    return {
        "zip_path": str(output / zip_name),
        "package_path": str(output / "cloud"),
        "deployment_version": deployment_version,
        "adapter_version": personal["version"],
        "source_commit": lock["commit"],
        "app_binding_preserved": True,
        "plugin_identity_preserved": True,
        "files_packaged": len(files),
        "base_files_validated": checked["files_checked"],
        "uploaded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-zip", required=True, type=Path, help="Private ZIP downloaded from the existing plugin.")
    parser.add_argument("--output-dir", type=Path, default=PRIVATE / "cloud-update")
    parser.add_argument("--upstream-dir", type=Path)
    args = parser.parse_args()
    try:
        result = prepare(original_zip=args.original_zip, output_dir=args.output_dir, upstream_dir=args.upstream_dir)
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, subprocess.CalledProcessError):
        # Backup JSON and subprocess diagnostics can contain a private binding.
        parser.exit(1, "Cloud update preparation failed. Check the private backup, output directory, and source revision. No upload was attempted.\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
