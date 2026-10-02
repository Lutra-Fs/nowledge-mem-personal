"""Small offline tests for upstream scope, candidate safety and deduplication."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "monitor_upstream.py"
SPEC = importlib.util.spec_from_file_location("monitor_upstream", SCRIPT)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class FakeGitHub:
    def __init__(self, base_sha):
        self.repository = "example/personal"
        self.base_sha = base_sha
        self.branch = None
        self.pr = None
        self.issue = None
        self.calls = []
        self.commits = 0

    def pages(self, path):
        if path.startswith("/pulls"):
            return iter([self.pr] if self.pr else [])
        return iter([self.issue] if self.issue else [])

    def request(self, method, path, data=None, **kwargs):
        self.calls.append((method, path, data))
        if method == "GET":
            if path == "":
                return {"default_branch": "main"}
            if path == "/git/ref/heads/main":
                return {"object": {"sha": self.base_sha}}
            if path.startswith("/git/ref/heads/automation"):
                return {"object": {"sha": self.branch}} if self.branch else None
            if path == f"/git/commits/{self.base_sha}":
                return {"tree": {"sha": "base-tree"}, "message": "Base"}
            if path.startswith("/git/commits/"):
                return {"tree": {"sha": "candidate-tree"},
                        "message": monitor.COMMIT_MARKER}
            if path.startswith("/git/trees/"):
                return {"truncated": False, "tree": []}
            if path.startswith("/compare/"):
                return {"files": [{"filename": "upstream.lock.json"}]}
        if path == "/git/blobs":
            return {"sha": "blob"}
        if path == "/git/trees":
            return {"sha": "candidate-tree"}
        if path == "/git/commits":
            self.commits += 1
            return {"sha": f"candidate-{self.commits}"}
        if path == "/git/refs" or path.startswith("/git/refs/heads/"):
            self.branch = data["sha"]
            return {}
        if path == "/pulls":
            self.pr = {**data, "number": 1, "html_url": "https://github.com/example/personal/pull/1"}
            return self.pr
        if path == "/issues":
            self.issue = {**data, "number": 2, "html_url": "https://github.com/example/personal/issues/2"}
            return self.issue
        if path == "/pulls/1":
            self.pr.update(data)
            return self.pr
        if path == "/issues/2":
            self.issue.update(data)
            return self.issue
        raise AssertionError((method, path))


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        monitor.git(self.upstream, "init", "-b", "main", "--quiet")
        monitor.git(self.upstream, "config", "user.email", "test@example.invalid")
        monitor.git(self.upstream, "config", "user.name", "Test")
        for package in ("local", "cloud"):
            path = self.upstream / package / ".codex-plugin" / "plugin.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"version": "0.1.0"}))
        self.commit(self.upstream)
        self.lock = {
            "repository": "https://github.com/example/upstream.git", "ref": "main",
            "commit": monitor.git(self.upstream, "rev-parse", "HEAD"),
            "packages": {kind: {"path": kind, "version": "0.1.0"}
                         for kind in ("local", "cloud")},
            "tracked_paths": ["local", "cloud"],
        }

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def commit(directory):
        monitor.git(directory, "add", ".")
        monitor.git(directory, "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Fixture")

    def test_unrelated_change_is_quiet(self):
        (self.upstream / "unrelated.txt").write_text("Unrelated")
        self.commit(self.upstream)
        report, candidate = monitor.inspect_upstream(self.upstream, self.lock)
        self.assertEqual(report["status"], "no_change")
        self.assertIsNone(candidate)

    def test_tracked_change_updates_exact_commit_and_version(self):
        (self.upstream / "local/.codex-plugin/plugin.json").write_text('{"version":"0.2.0"}')
        self.commit(self.upstream)
        report, candidate = monitor.inspect_upstream(self.upstream, self.lock)
        self.assertEqual(candidate["commit"], monitor.git(self.upstream, "rev-parse", "HEAD"))
        self.assertEqual(candidate["packages"]["local"]["version"], "0.2.0")
        self.assertEqual(report["changed_files"], ["local/.codex-plugin/plugin.json"])
        self.assertEqual(self.lock["packages"]["local"]["version"], "0.1.0")

    def test_removed_manifest_is_an_incompatible_candidate(self):
        (self.upstream / "local/.codex-plugin/plugin.json").unlink()
        self.commit(self.upstream)
        report, candidate = monitor.inspect_upstream(self.upstream, self.lock)
        self.assertIn("inspection_error", report)
        self.assertIsNotNone(candidate)

    def test_candidate_rebuild_has_no_writer_credential(self):
        base = self.root / "personal"
        base.mkdir()
        monitor.git(base, "init", "--quiet")
        (base / "scripts").mkdir()
        (base / "tests").mkdir()
        (base / "personal.json").write_text('{"version":"0.1.0"}')
        (base / "tests/test_smoke.py").write_text(
            "import unittest\nclass Smoke(unittest.TestCase):\n"
            "    def test_ready(self):\n        self.assertTrue(True)\n")
        (base / "scripts/build.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "assert 'GITHUB_TOKEN' not in os.environ\n"
            "assert 'GITHUB_ENV' not in os.environ\n"
            "Path('packages').mkdir(exist_ok=True)\n"
            "Path('packages/generated.txt').write_text('fresh candidate')\n")
        (base / "scripts/validate.py").write_text(
            "from pathlib import Path\nassert Path('packages/generated.txt').read_text() == 'fresh candidate'\n")
        (base / "scripts/check_public.py").write_text("print('Public fixture passed')\n")
        with patch.dict(os.environ, {"GITHUB_TOKEN": "unit-test-token", "GITHUB_ENV": "fixture"}):
            workspace, logs = monitor.validate_candidate(base, self.upstream, self.lock, self.root)
        self.assertEqual(monitor.output_files(workspace)["packages/generated.txt"][0], b"fresh candidate")
        self.assertEqual(json.loads((workspace / "personal.json").read_text())["version"], "0.1.1")
        self.assertIn("Public fixture passed", logs)
        self.assertFalse((base / "packages").exists())

    def test_one_incompatibility_issue_on_rerun(self):
        report, _ = monitor.inspect_upstream(self.upstream, self.lock)
        report["error"] = "Adapter contract changed"
        api = FakeGitHub(self.lock["commit"])
        first = monitor.report_incompatibility(api, report)
        second = monitor.report_incompatibility(api, report)
        self.assertEqual(first, second)
        self.assertEqual(sum(method == "POST" for method, _, _ in api.calls), 1)
        self.assertEqual(sum(method == "PATCH" for method, _, _ in api.calls), 0)

    def test_one_update_branch_and_pr_on_rerun(self):
        report, _ = monitor.inspect_upstream(self.upstream, self.lock)
        (self.upstream / "upstream.lock.json").write_text(json.dumps(self.lock))
        (self.upstream / "personal.json").write_text('{"version":"0.1.1"}')
        (self.upstream / "packages").mkdir()
        (self.upstream / "packages/template.txt").write_text("public template")
        api = FakeGitHub(self.lock["commit"])
        first = monitor.publish_candidate(api, self.upstream, report, self.upstream)
        second = monitor.publish_candidate(api, self.upstream, report, self.upstream)
        self.assertEqual(first, second)
        self.assertEqual(api.commits, 1)
        self.assertEqual(sum(path == "/pulls" and method == "POST"
                             for method, path, _ in api.calls), 1)
        tree = next(data for method, path, data in api.calls if path == "/git/trees")
        self.assertEqual({item["path"] for item in tree["tree"]},
                         {"upstream.lock.json", "personal.json", "packages/template.txt"})

    def test_closed_candidate_is_not_published_again(self):
        report, _ = monitor.inspect_upstream(self.upstream, self.lock)
        api = FakeGitHub(self.lock["commit"])
        api.pr = {"state": "closed", "body": monitor.PR_MARKER + report["compare_url"],
                  "html_url": "https://github.com/example/personal/pull/1"}
        monitor.publish_candidate(api, self.upstream, report, self.upstream)
        self.assertEqual(report["status"], "closed_pr_held")
        self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
