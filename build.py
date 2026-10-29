"""Build the deterministic BrainRoad desktop source download and its checksum manifest.

The plugin itself installs from Git through Hermes' own reviewed installer. This ZIP is the
same files for people who prefer a download, and lets anyone check that the published source
matches what the repository contains.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
# Deliberately enumerated: a developer's .env, browser state or a stray script can never
# silently become part of the download.
SOURCES = (
    "LICENSE", "NOTICE.md", "README.md", "release.json", "plugin.yaml", "__init__.py",
    "skills/computer-help/SKILL.md", "skills/browser-work/SKILL.md",
    "skills/code-work/SKILL.md", "skills/first-task/SKILL.md",
    "dashboard/manifest.json", "dashboard/plugin_api.py", "dashboard/phone_link.py",
    "desktop/plugin.js", "build.py", "verify_upstream.py",
    "tests/test_package.py", "tests/test_phone_link.py", ".github/workflows/test.yml",
)


def build(output: Path) -> dict:
    release = json.loads((ROOT / "release.json").read_text())
    for name in SOURCES:
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError(f"Source must be a regular, in-tree file: {name}")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as source:
        for name in sorted(SOURCES):
            info = zipfile.ZipInfo(f'brainroad-desktop-{release["version"]}/{name}', (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            source.writestr(info, (ROOT / name).read_bytes())
    data = archive.getvalue()
    output.mkdir(parents=True, exist_ok=True)
    (output / release["sourceArchive"]).write_bytes(data)
    manifest = {**release, "kind": "hermes-plugin", "files": sorted(SOURCES),
                "sourceSha256": hashlib.sha256(data).hexdigest(), "sourceBytes": len(data)}
    (output / "brainroad-desktop.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "public/downloads")
    args = parser.parse_args()
    result = build(args.output)
    print(f'{result["sourceArchive"]}: {result["sourceBytes"]} bytes, SHA-256 {result["sourceSha256"]}')
