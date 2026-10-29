"""Load BrainRoad into a real Hermes source checkout, with no model call and no network.

Checks Hermes' own plugin discovery, the four registered skills, the rendered guidance
section, the backend's import and status route, and that Hermes' ``config set`` accepts and
removes every setting pairing writes. Run with Hermes' Python environment:

    python verify_upstream.py --hermes-source PATH --scratch NEW_EMPTY_DIR
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build import SOURCES

ROOT = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--hermes-source", type=Path, required=True)
parser.add_argument("--scratch", type=Path, required=True)
args = parser.parse_args()
scratch = args.scratch.resolve()
scratch.mkdir(parents=True, exist_ok=False)
home = scratch / "hermes-home"
plugin = home / "plugins" / "brainroad"
for name in SOURCES:
    (plugin / name).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / name, plugin / name)
(home / "config.yaml").write_text("plugins:\n  enabled:\n    - brainroad\n")
environment = {**os.environ, "HERMES_HOME": str(home), "PYTHONPATH": str(args.hermes_source.resolve()),
               "HERMES_MANAGED_DIR": str(scratch / "no-managed-settings"), "PYTHONDONTWRITEBYTECODE": "1",
               "BRAINROAD_URL": "https://app.brainroad.com"}


def run(script: str) -> dict:
    result = subprocess.run([sys.executable, "-c", script], env=environment, cwd=args.hermes_source,
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise SystemExit(f"FAILED:\n{result.stdout[-2000:]}\n{result.stderr[-4000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


loaded = run(r'''
import json
from hermes_cli.plugins import discover_plugins, get_plugin_manager, render_system_prompt_sections
discover_plugins(force=True)
manager = get_plugin_manager()
skills = sorted(k for k in manager._plugin_skills if k.startswith("brainroad:"))
sections = [s for s in render_system_prompt_sections({}) if getattr(s, "id", "") == "brainroad.guidance"]
from tools.skills_tool import skills_list
listed = sorted(s["name"] for s in json.loads(skills_list()).get("skills", []) if s["name"].startswith("brainroad:"))
print(json.dumps({"skills": skills, "listed": listed, "guidance": len(sections), "chars": len(sections[0].content) if sections else 0}))
''')
expected = ["brainroad:browser-work", "brainroad:code-work", "brainroad:computer-help", "brainroad:first-task"]
assert loaded["skills"] == expected, loaded
assert loaded["listed"] == expected, loaded
assert loaded["guidance"] == 1 and 0 < loaded["chars"] < 2000, loaded

backend = run(r'''
import importlib.util, json, sys
from pathlib import Path
from hermes_constants import get_hermes_home
api = Path(get_hermes_home()) / "plugins/brainroad/dashboard/plugin_api.py"
spec = importlib.util.spec_from_file_location("hermes_dashboard_plugin_brainroad", api)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
status = module.status()
routes = sorted(r.path for r in module.router.routes)
print(json.dumps({"state": status["state"], "paired": status["paired"], "connector": status["connectorHere"],
                  "computer": status["computer"]["platform"], "routes": routes}))
''')
assert backend["paired"] is False and backend["state"] == "off" and backend["connector"] is True, backend
assert "/status" in backend["routes"] and "/phone/pair" in backend["routes"], backend

settings = run(r'''
import importlib.util, json, sys
from pathlib import Path
from hermes_constants import get_hermes_home
home = Path(get_hermes_home())
spec = importlib.util.spec_from_file_location("brainroad_phone_link", home / "plugins/brainroad/dashboard/phone_link.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
write = module.hermes_config_writer(home)
values = {"webapp.enabled": "true", "webapp.host": "127.0.0.1",
          "webapp.public_url": "https://app.brainroad.com/computers/00000000-0000-4000-8000-000000000000/agent",
          "dashboard.oauth.self_hosted.issuer": "https://app.brainroad.com/oidc",
          "dashboard.oauth.self_hosted.client_id": "device-00000000-0000-4000-8000-000000000000",
          "dashboard.oauth.self_hosted.scopes": "openid profile email"}
for key, value in values.items():
    write(key, value)
from hermes_cli.config import read_user_config_raw
written = read_user_config_raw(home / "config.yaml")
from gateway.webapp_listener import webapp_settings
listener = webapp_settings(home)
for key in values:
    write(key, None)
removed = read_user_config_raw(home / "config.yaml")
print(json.dumps({"public_url": written["webapp"]["public_url"], "enabled": written["webapp"]["enabled"],
                  "issuer": written["dashboard"]["oauth"]["self_hosted"]["issuer"],
                  "listener": [listener.enabled, listener.host, listener.public_url, listener.reason],
                  "removed": "public_url" not in (removed.get("webapp") or {})}))
''')
assert settings["enabled"] is True and settings["issuer"].endswith("/oidc"), settings
assert settings["listener"][:2] == [True, "127.0.0.1"] and settings["listener"][3] is None, settings
assert settings["removed"] is True, settings
print(json.dumps({"plugin": loaded, "backend": backend, "settings": settings}, indent=2))
