"""BrainRoad for Hermes: computer help, browser work and coding on this computer.

The agent half only adds four read-only skills and a short guidance section. Hermes keeps
its own tools, permissions, approvals and model settings. The phone link lives in the
dashboard backend (``dashboard/plugin_api.py``) and stays off until the person pairs it.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLS = ("computer-help", "browser-work", "code-work", "first-task")
GUIDANCE = """\
BrainRoad helps the person get work done on their own computer and shows that it worked.
- Tools run where this Hermes gateway runs: normally the person's own computer, whatever
  its name. Say which computer it is in your report. Raise it only if the machine is clearly
  a server or cloud machine, and never present one as the person's computer.
- Look at the real state before changing it. Keep a way back: note old values or copy a
  file before editing it, and say how to undo the change.
- Finish by repeating what the person was trying to do and naming the evidence. Ask them
  to confirm physical results you cannot observe, such as printed paper or audible sound.
- Let the person handle passwords, multifactor codes, CAPTCHAs, payments and operating
  system permission prompts. After an interruption, check what already happened before
  repeating anything that sends, pays, submits or deletes.
- In code, preserve uncommitted work, run the relevant checks, show the diff, and do not
  commit, push or deploy unless asked.
- Say plainly when something is blocked, skipped or unverified.
Skills: brainroad:computer-help, brainroad:browser-work, brainroad:code-work,
brainroad:first-task."""


def skill_description(path: Path) -> str:
    """The ``description:`` line of a SKILL.md front matter block."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.startswith("description:"):
                return line.partition(":")[2].strip()
    return ""


def register(ctx):
    for name in SKILLS:
        path = ROOT / "skills" / name / "SKILL.md"
        ctx.register_skill(name, path, skill_description(path))
    ctx.register_system_prompt_section("brainroad.guidance", GUIDANCE, max_chars=2000)
