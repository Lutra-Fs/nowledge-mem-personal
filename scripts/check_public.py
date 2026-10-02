#!/usr/bin/env python3
"""Check tracked and publishable files for live bindings and private data."""

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "live App binding": re.compile(r"(?:plugin_)?asdk_app_[0-9a-f]{16,}", re.I),
    "GitHub credential": re.compile(r"gh[pousr]_[A-Za-z0-9]{25,}"),
    "Mem credential": re.compile(r"\bnmem_[A-Za-z0-9_-]{24,}\b"),
    "personal home path": re.compile(r"/Users/[A-Za-z][^/\s]+/"),
    "memory UUID": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
}


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, check=True, stdout=subprocess.PIPE,
    )
    paths = set(result.stdout.decode().split("\0")) - {""}
    problems = []
    for name in sorted(paths):
        path = ROOT / name
        if not path.is_file():
            continue
        if name.startswith((".private/", ".cache/", "upstream/", "dist/")):
            problems.append(f"{name}: generated or private directory is tracked")
            continue
        content = path.read_bytes()
        if b"\0" in content:
            continue
        for label, pattern in PATTERNS.items():
            for number, line in enumerate(content.decode("utf-8", errors="replace").splitlines(), 1):
                if pattern.search(line):
                    problems.append(f"{name}:{number}: {label}")
    if problems:
        print("Public-content check failed:")
        print("\n".join(problems))
        return 1
    print(f"Public-content check passed for {len(paths)} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
