#!/usr/bin/env python3
"""Validate an upstream candidate; publish only with an explicit --publish.

The monitor changes one lock and its generated public packages. It never installs
plugins, merges a PR, or calls Mem. An existing --upstream-dir is read as supplied;
fetch it first when you want a fresh remote ref. No third-party Python modules.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


BRANCH = "automation/upstream-update"
PR_MARKER = "<!-- nowledge-personal-upstream-monitor -->"
ISSUE_MARKER = "<!-- nowledge-personal-upstream-incompatible -->"
COMMIT_MARKER = "[nowledge-personal-upstream-monitor]"


class InfrastructureError(RuntimeError):
    """A Git fetch/object failure is not a finding about upstream compatibility."""


def run(args: list[str], cwd: Path, *, env: dict | None = None) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=600)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{args[0]} exceeded the 10 minute command limit.") from error
    if result.returncode:
        raise RuntimeError(f"{args[0]} exited {result.returncode}:\n"
                           f"{result.stdout}{result.stderr}"[-10000:])
    return result.stdout.strip()


def git(directory: Path, *args: str) -> str:
    return run(["git", *args], directory)


def read_lock(base: Path) -> dict:
    lock = json.loads((base / "upstream.lock.json").read_text())
    if not re.fullmatch(r"[0-9a-f]{40}", lock["commit"]):
        raise ValueError("The lock must contain a full upstream commit SHA.")
    if not lock.get("tracked_paths"):
        raise ValueError("The lock must contain tracked_paths.")
    for name in [*lock["tracked_paths"],
                 *(item["path"] for item in lock["packages"].values())]:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name.startswith("-"):
            raise ValueError("Lock paths must stay inside the upstream tree.")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", lock.get("ref", "main")):
        raise ValueError("Unsupported upstream ref.")
    return lock


def upstream_head(upstream: Path, ref: str) -> str:
    for name in (f"refs/remotes/origin/{ref}", ref):
        try:
            return git(upstream, "rev-parse", "--verify", f"{name}^{{commit}}")
        except RuntimeError:
            pass
    raise ValueError(f"Upstream ref is unavailable: {ref}")


def inspect_upstream(upstream: Path, lock: dict) -> tuple[dict, dict | None]:
    head = upstream_head(upstream, lock.get("ref", "main"))
    changed = git(upstream, "diff", "--name-only", "--no-renames",
                  lock["commit"], head, "--", *lock["tracked_paths"]).splitlines()
    repository = lock["repository"].removesuffix(".git")
    report = {
        "status": "candidate" if changed else "no_change",
        "locked_commit": lock["commit"], "candidate_commit": head,
        "changed_files": changed,
        "compare_url": f"{repository}/compare/{lock['commit']}...{head}",
    }
    if not changed:
        return report, None
    candidate = copy.deepcopy(lock)
    candidate["commit"] = head
    try:
        for item in candidate["packages"].values():
            manifest = f"{item['path']}/.codex-plugin/plugin.json"
            data = json.loads(git(upstream, "show", f"{head}:{manifest}"))
            if not isinstance(data.get("version"), str) or not data["version"]:
                raise ValueError(f"Upstream package has no version: {manifest}")
            item["version"] = data["version"]
    except (RuntimeError, ValueError, KeyError) as error:
        report["inspection_error"] = str(error)
    return report, candidate


def public_source_copy(base: Path, target: Path) -> None:
    """Copy tracked/nonignored source; never copy ignored private outputs."""
    names = run(["git", "ls-files", "-z", "--cached", "--others",
                 "--exclude-standard"], base).split("\0")
    for name in names:
        if not name or name.startswith((".private/", "dist/", "upstream/")):
            continue
        source = base / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Public source is not a regular file: {name}")
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def validation_env() -> dict:
    # Writer credentials remain only in this process, never in build children.
    forbidden = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY")
    return {key: value for key, value in os.environ.items()
            if not any(part in key.upper() for part in forbidden)
            and key not in {"GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH",
                            "GITHUB_STEP_SUMMARY"}}


def bump_personal_version(workspace: Path) -> str:
    path = workspace / "personal.json"
    config = json.loads(path.read_text())
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", config["version"])
    if not match:
        raise ValueError("The personal version needs a manual update; expected ordinary x.y.z.")
    major, minor, patch = map(int, match.groups())
    config["version"] = f"{major}.{minor}.{patch + 1}"
    path.write_text(json.dumps(config, indent=2) + "\n")
    return config["version"]


def validate_candidate(base: Path, upstream: Path, candidate: dict,
                       temporary: Path) -> tuple[Path, str]:
    workspace = temporary / "candidate"
    workspace.mkdir()
    public_source_copy(base, workspace)
    git(workspace, "init", "--quiet")
    (workspace / "upstream.lock.json").write_text(
        json.dumps(candidate, indent=2) + "\n")
    bump_personal_version(workspace)
    # The trusted builder reads the exact locked Git objects. It needs no checkout.
    # Reuse the source's promisor configuration; a --shared clone loses it.
    checkout = upstream
    env = validation_env()
    commands = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        [sys.executable, "scripts/build.py", "--upstream-dir", str(checkout),
         "--output-dir", "packages"],
        [sys.executable, "scripts/validate.py", "packages", "--allow-template"],
        [sys.executable, "scripts/check_public.py"],
    ]
    logs = []
    try:
        for command in commands:
            logs.append(run(command, workspace, env=env))
    except RuntimeError as error:
        if "an upstream Git operation failed" in str(error):
            raise InfrastructureError("Candidate Git objects could not be read. "
                                      "Retry the upstream fetch; no compatibility issue was published.") from error
        raise RuntimeError(str(error).replace(str(workspace), "<candidate>")
                           .replace(str(checkout), "<upstream>")) from error
    logs = "\n".join(logs).replace(str(workspace), "<candidate>").replace(str(upstream), "<upstream>")
    return workspace, logs[-6000:]


def output_files(workspace: Path) -> dict[str, tuple[bytes, str]]:
    files = {name: ((workspace / name).read_bytes(), "100644")
             for name in ("upstream.lock.json", "personal.json")}
    packages = workspace / "packages"
    if not packages.is_dir():
        raise ValueError("Candidate did not build the public packages directory.")
    for path in sorted(packages.rglob("*")):
        if path.is_symlink():
            raise ValueError("Generated public packages must not contain symlinks.")
        if path.is_file():
            mode = "100755" if path.stat().st_mode & 0o111 else "100644"
            files[path.relative_to(workspace).as_posix()] = (path.read_bytes(), mode)
    return files


class GitHub:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Set GITHUB_REPOSITORY to owner/repository.")
        self.repository = repository
        self.prefix = f"/repos/{repository}"
        self.token = token

    def request(self, method: str, path: str, data: dict | None = None,
                *, missing_ok: bool = False):
        request = urllib.request.Request(
            "https://api.github.com" + self.prefix + path,
            data=None if data is None else json.dumps(data).encode(), method=method,
            headers={"Accept": "application/vnd.github+json",
                     "Authorization": f"Bearer {self.token}",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "nowledge-personal-upstream-monitor"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            # Never print request headers or token, including error responses.
            raise RuntimeError(f"GitHub {method} {path} returned HTTP {error.code}.") from error

    def pages(self, path: str):
        separator = "&" if "?" in path else "?"
        page = 1
        while True:
            items = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            yield from items
            if len(items) < 100:
                return
            page += 1


def issue_body(report: dict) -> str:
    changed = "\n".join(f"- `{name}`" for name in report["changed_files"])
    return (f"{ISSUE_MARKER}\n\nThe upstream candidate did not pass the local "
            "package checks. No update PR was created for this candidate.\n\n"
            f"Locked commit: `{report['locked_commit']}`\n\n"
            f"Candidate: `{report['candidate_commit']}`\n\n"
            f"[Compare upstream]({report['compare_url']})\n\n"
            f"Changed tracked files:\n{changed}\n\n"
            f"Validation result:\n```text\n{report.get('error', 'Unknown failure')[:6000]}\n```\n\n"
            "Repair the personal adapter or lock before a manual retry. "
            "The monitor does not merge, install, or modify Mem data.")


def report_incompatibility(api: GitHub, report: dict) -> str:
    body = issue_body(report)
    existing = next((item for item in api.pages("/issues?state=all")
                     if not item.get("pull_request")
                     and ISSUE_MARKER in (item.get("body") or "")), None)
    title = "Upstream update requires an adapter change"
    if existing:
        if existing.get("state") == "closed" and report["candidate_commit"] in (existing.get("body") or ""):
            report["status"] = "closed_issue_held"
            return existing["html_url"]
        if existing.get("body") != body:
            api.request("PATCH", f"/issues/{existing['number']}",
                        {"title": title, "body": body, "state": "open"})
        return existing["html_url"]
    return api.request("POST", "/issues", {"title": title, "body": body})["html_url"]


def is_output_path(path: str) -> bool:
    return path in {"upstream.lock.json", "personal.json"} or path.startswith("packages/")


def publish_candidate(api: GitHub, base: Path, report: dict, workspace: Path) -> str:
    head = urllib.parse.quote(api.repository.split("/")[0] + ":" + BRANCH, safe="")
    pull_requests = list(api.pages(f"/pulls?state=all&head={head}"))
    existing = next((item for item in pull_requests if item.get("state", "open") == "open"), None)
    if existing and PR_MARKER not in (existing.get("body") or ""):
        raise RuntimeError("The update PR has no monitor marker. Refusing to edit it.")
    if not existing:
        held = next((item for item in pull_requests
                     if not item.get("merged_at") and PR_MARKER in (item.get("body") or "")
                     and report["compare_url"] in (item.get("body") or "")), None)
        if held:
            report["status"] = "closed_pr_held"
            return held["html_url"]
    repository = api.request("GET", "")
    default_branch = repository["default_branch"]
    base_ref = api.request("GET", "/git/ref/heads/" + urllib.parse.quote(default_branch, safe=""))
    base_sha = base_ref["object"]["sha"]
    if git(base, "rev-parse", "HEAD") != base_sha:
        raise RuntimeError("Default branch changed during this run. Retry from its latest commit.")
    base_commit = api.request("GET", f"/git/commits/{base_sha}")
    base_tree = api.request("GET", f"/git/trees/{base_commit['tree']['sha']}?recursive=1")
    if base_tree.get("truncated"):
        raise RuntimeError("The GitHub tree is incomplete; no branch was updated.")
    old_files = {item["path"]: item for item in base_tree["tree"]
                 if item["type"] == "blob" and is_output_path(item["path"])}
    branch_path = "/git/ref/heads/" + urllib.parse.quote(BRANCH, safe="")
    branch = api.request("GET", branch_path, missing_ok=True)
    previous = None
    if branch:
        previous = branch["object"]["sha"]
        commit = api.request("GET", f"/git/commits/{previous}")
        if COMMIT_MARKER not in commit["message"]:
            raise RuntimeError("The update branch has a user commit. Refusing to replace it.")
        comparison = api.request("GET", f"/compare/{base_sha}...{previous}")
        if any(not is_output_path(item["filename"]) for item in comparison.get("files", [])):
            raise RuntimeError("The update branch has changes outside the allowed outputs.")
    files = output_files(workspace)
    entries = []
    for name, (content, mode) in files.items():
        blob_sha = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        old = old_files.get(name)
        if old and old["sha"] == blob_sha and old["mode"] == mode:
            continue
        blob = api.request("POST", "/git/blobs", {
            "content": base64.b64encode(content).decode(), "encoding": "base64"})
        entries.append({"path": name, "mode": mode, "type": "blob", "sha": blob["sha"]})
    for name, item in old_files.items():
        if name not in files:
            entries.append({"path": name, "mode": item["mode"], "type": "blob", "sha": None})
    tree = api.request("POST", "/git/trees", {
        "base_tree": base_commit["tree"]["sha"], "tree": entries})
    if not previous or commit["tree"]["sha"] != tree["sha"]:
        parents = [base_sha] if not previous else list(dict.fromkeys([previous, base_sha]))
        commit = api.request("POST", "/git/commits", {
            "message": f"chore: update Nowledge upstream\n\n{COMMIT_MARKER}\n"
                       f"Upstream: {report['candidate_commit']}",
            "tree": tree["sha"], "parents": parents})
        if previous:
            # Fast-forward only. A concurrent/manual edit causes an API rejection.
            api.request("PATCH", branch_path.replace("/git/ref/", "/git/refs/"),
                        {"sha": commit["sha"], "force": False})
        else:
            api.request("POST", "/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
    changed = "\n".join(f"- `{name}`" for name in report["changed_files"])
    body = (f"{PR_MARKER}\n\nUpdate the locked upstream revision, increase the personal patch version, and rebuild the "
            "public local package and unbound cloud template. Personal adapters remain in the source.\n\n"
            f"[Compare upstream]({report['compare_url']})\n\n"
            f"Changed tracked files:\n{changed}\n\n"
            "Validation: stdlib tests, candidate build, and template package validation passed "
            "before this PR was created or updated.\n\n"
            "Review the upstream changes and generated packages before merging. "
            "This PR does not install a plugin or change Mem data. "
            "GitHub may require approval before running checks on a GITHUB_TOKEN-created PR.")
    title = f"Update Nowledge upstream to {report['candidate_commit'][:12]}"
    if existing:
        if existing.get("title") != title or existing.get("body") != body:
            api.request("PATCH", f"/pulls/{existing['number']}", {"title": title, "body": body})
        return existing["html_url"]
    return api.request("POST", "/pulls", {
        "title": title, "body": body, "head": BRANCH, "base": default_branch})["html_url"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--upstream-dir", type=Path)
    parser.add_argument("--report", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default; no GitHub writes")
    mode.add_argument("--publish", action="store_true", help="use only GITHUB_TOKEN to update one PR or issue")
    args = parser.parse_args(argv)
    base = args.base_dir.resolve()
    report = {"status": "error", "published": False}
    try:
        lock = read_lock(base)
        with tempfile.TemporaryDirectory(prefix="nowledge-monitor-") as name:
            temporary = Path(name)
            upstream = args.upstream_dir.resolve() if args.upstream_dir else temporary / "upstream"
            if args.upstream_dir is None:
                git(temporary, "clone", "--filter=blob:none", "--no-checkout", lock["repository"], str(upstream))
            report, candidate = inspect_upstream(upstream, lock)
            report["published"] = False
            if candidate:
                try:
                    if report.get("inspection_error"):
                        raise RuntimeError(report["inspection_error"])
                    workspace, logs = validate_candidate(base, upstream, candidate, temporary)
                    personal = json.loads((workspace / "personal.json").read_text())
                    report.update(status="validated", personal_version=personal["version"], validation=logs)
                except InfrastructureError:
                    raise
                except (RuntimeError, ValueError, OSError) as error:
                    report.update(status="incompatible", error=str(error))
                if args.publish:
                    token = os.environ.get("GITHUB_TOKEN")
                    if not token:
                        raise ValueError("--publish requires GITHUB_TOKEN; no PAT or GH_TOKEN fallback.")
                    api = GitHub(os.environ.get("GITHUB_REPOSITORY", ""), token)
                    if report["status"] == "incompatible":
                        report["url"] = report_incompatibility(api, report)
                    else:
                        report["url"] = publish_candidate(api, base, report, workspace)
                    report["published"] = not report["status"].startswith("closed_")
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        report.update(status="error", error=str(error))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "no_change":
        print(json.dumps(report, indent=2))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a") as file:
                file.write(f"## Upstream monitor: {report['status']}\n\n")
                if report.get("url"):
                    file.write(f"[Review the result]({report['url']})\n")
    # An incompatibility has its own deduplicated issue, so avoid daily failed-run spam.
    return 1 if report["status"] == "error" or (
        report["status"] == "incompatible" and not args.publish) else 0


if __name__ == "__main__":
    raise SystemExit(main())
