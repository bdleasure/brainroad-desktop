"""Checks the plugin package and its reproducible source download, without Hermes installed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build import SOURCES, build  # noqa: E402


def load_plugin():
    spec = importlib.util.spec_from_file_location("brainroad_plugin", ROOT / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeContext:
    def __init__(self):
        self.skills, self.sections = {}, {}

    def register_skill(self, name, path, description=""):
        self.skills[name] = (Path(path), description)

    def register_system_prompt_section(self, id, content, *, max_chars=4000):
        assert len(content) <= max_chars, (id, len(content), max_chars)
        self.sections[id] = content


class PackageTests(unittest.TestCase):
    def test_source_download_is_reproducible_from_itself(self):
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "first"
            manifest = build(first)
            data = (first / manifest["sourceArchive"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["sourceSha256"])
            with zipfile.ZipFile(first / manifest["sourceArchive"]) as source:
                names = source.namelist()
                source.extractall(Path(temp) / "unpacked")
            prefix = f'brainroad-desktop-{manifest["version"]}/'
            self.assertEqual(sorted(names), sorted(prefix + name for name in SOURCES))
            rebuilt = Path(temp) / "rebuilt"
            subprocess.run([sys.executable, str(Path(temp) / "unpacked" / prefix / "build.py"),
                            "--output", str(rebuilt)], check=True, capture_output=True)
            for name in (manifest["sourceArchive"], "brainroad-desktop.json"):
                self.assertEqual((first / name).read_bytes(), (rebuilt / name).read_bytes(), name)

    def test_every_repository_file_is_published_and_nothing_private_is(self):
        tracked = {str(path.relative_to(ROOT)).replace("\\", "/") for path in ROOT.rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts and path.name != ".gitignore"
                   and ".git" not in path.parts}
        # .github is the repository's CI and is published too; .git and caches are not.
        self.assertEqual(tracked, set(SOURCES))
        forbidden = re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}", re.I)
        for name in SOURCES:
            self.assertIsNone(forbidden.search((ROOT / name).read_text(encoding="utf-8")), name)

    def test_agent_half_registers_four_skills_and_bounded_guidance(self):
        ctx = FakeContext()
        load_plugin().register(ctx)
        self.assertEqual(set(ctx.skills), {"computer-help", "browser-work", "code-work", "first-task"})
        for name, (path, description) in ctx.skills.items():
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith(f"---\nname: {name}\n"), name)
            self.assertGreater(len(description), 40, name)
        guidance = ctx.sections["brainroad.guidance"]
        self.assertLess(len(guidance), 2000)
        for skill in ctx.skills:
            self.assertIn(f"brainroad:{skill}", guidance)

    def test_manifests_agree_on_name_and_version(self):
        release = json.loads((ROOT / "release.json").read_text())
        dashboard = json.loads((ROOT / "dashboard/manifest.json").read_text())
        plugin_yaml = (ROOT / "plugin.yaml").read_text()
        self.assertIn("name: brainroad\n", plugin_yaml)
        self.assertIn(f'version: {release["version"]}\n', plugin_yaml)
        self.assertEqual((dashboard["name"], dashboard["version"], dashboard["api"]),
                         ("brainroad", release["version"], "plugin_api.py"))
        phone_link = (ROOT / "dashboard/phone_link.py").read_text()
        self.assertIn(f'VERSION = "{release["version"]}"', phone_link)

    def test_desktop_half_uses_only_the_plugin_sdk(self):
        source = (ROOT / "desktop/plugin.js").read_text()
        imports = set(re.findall(r"^import [^;]*? from '([^']+)'", source, re.M | re.S))
        self.assertEqual(imports, {"@hermes/plugin-sdk", "react", "react/jsx-runtime"})
        self.assertNotIn("document.querySelector", source)
        self.assertIn("id: 'brainroad'", source)

    def test_every_change_route_is_native_app_only(self):
        source = (ROOT / "dashboard/plugin_api.py").read_text()
        routes = re.findall(r'@router\.(get|post)\("([^"]+)"(.*?)\)\n', source)
        self.assertTrue(routes)
        for method, path, rest in routes:
            if method == "post":
                self.assertIn("dependencies=native", rest, path)
            else:
                self.assertEqual(path, "/status")


if __name__ == "__main__":
    unittest.main()
