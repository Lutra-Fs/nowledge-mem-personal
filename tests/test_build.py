"""Small checks for public templates, private bindings, and package integrity."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


builder = module("build")
validator = module("validate")


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="nmem-personal-tests-")
        cls.base = Path(cls.temporary.name)
        source = os.environ.get("NMEM_TEST_UPSTREAM")
        cls.source = Path(source) if source else None
        cls.output = builder.build(upstream_dir=cls.source, output_dir=cls.base / "first")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_template_needs_explicit_flag_and_build_is_reproducible(self):
        with self.assertRaisesRegex(ValueError, "unbound template"):
            validator.validate(self.output)
        self.assertEqual(validator.validate(self.output, allow_template=True)["cloud_binding"], "template")
        second = builder.build(upstream_dir=self.source, output_dir=self.base / "second")
        self.assertEqual(
            (self.output / "build-receipt.json").read_bytes(),
            (second / "build-receipt.json").read_bytes(),
        )

    def test_bound_id_requires_private_output(self):
        # A synthetic ID tests format and containment. It is never an App connection.
        synthetic = "asdk_app_" + "0" * 32
        with self.assertRaisesRegex(ValueError, "inside ignored .private"):
            builder.build(upstream_dir=self.source, output_dir=self.base / "bound", app_id=synthetic)
        private_root = ROOT / ".private"
        private_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="test-bound-", dir=private_root) as temporary:
            bound = builder.build(upstream_dir=self.source, output_dir=Path(temporary) / "output", app_id="plugin_" + synthetic)
            self.assertEqual(validator.validate(bound)["cloud_binding"], "bound")
            app = json.loads((bound / "cloud" / ".app.json").read_text())
            self.assertEqual(app["apps"]["nowledge-mem"]["id"], synthetic)

    def test_manifest_path_escape_and_file_change_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "escapes"):
            validator.contained(self.output / "cloud", "../../AGENTS.md")
        skill = self.output / "cloud" / "skills" / "nowledge-mem" / "SKILL.md"
        before = skill.read_bytes()
        try:
            skill.write_bytes(before + b"\nUnexpected edit.\n")
            with self.assertRaisesRegex(ValueError, "build receipt"):
                validator.validate(self.output, allow_template=True)
        finally:
            skill.write_bytes(before)


if __name__ == "__main__":
    unittest.main()
