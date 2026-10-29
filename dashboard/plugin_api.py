"""BrainRoad backend for Hermes Desktop, mounted at /api/plugins/brainroad/.

Reading status is allowed to any signed-in Hermes surface. Every change (pairing, turning
the phone link on or off, disconnecting) is accepted only from the native Hermes app on this
computer, the same rule Hermes applies to its own Web Access settings: a browser tab, which
may be the relayed phone itself, cannot change what this computer exposes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel


def _load_phone_link():
    name = "brainroad_phone_link"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("phone_link.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


phone_link = _load_phone_link()


def _gateway_home() -> Path:
    try:
        from hermes_cli.webapp_access import gateway_home
        return Path(gateway_home())
    except Exception:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())


def _read_config(home: Path):
    def read() -> dict:
        from hermes_constants import get_hermes_home
        from hermes_cli.config import load_config_readonly, read_user_config_raw
        if Path(get_hermes_home()).resolve() == home.resolve():
            return load_config_readonly()
        return read_user_config_raw(home / "config.yaml")
    return read


def _plugin_enabled(read) -> bool:
    plugins = (read() or {}).get("plugins") or {}
    enabled = plugins.get("enabled") or []
    disabled = plugins.get("disabled") or []
    return "brainroad" in enabled and "brainroad" not in disabled


def _notify(status: dict) -> None:
    from hermes_cli.plugin_events import broadcast_plugin_event
    broadcast_plugin_event("brainroad", "phone.changed", {"state": status.get("state")})


_home = _gateway_home()
_reader = _read_config(_home)
link = phone_link.link_for(_home, read_config=_reader, plugin_enabled=lambda: _plugin_enabled(_reader),
                           notify=_notify)
link.start()


def native_app_only(request: Request) -> None:
    """Hermes' own rule for Web Access: only a request carrying the native app's grant."""
    try:
        from hermes_cli.web_routers.webapp_access import owner_on_this_machine
    except ImportError:
        owner_on_this_machine = None
    if owner_on_this_machine is not None:
        owner_on_this_machine(request)
    elif not getattr(request.state, "native_http_principal", None):
        raise HTTPException(status_code=403, detail="Change this from the Hermes app on this computer.")


router = APIRouter()
native = [Depends(native_app_only)]


class Enabled(BaseModel):
    enabled: bool


def _run(action):
    try:
        return action()
    except phone_link.PhoneLinkError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status")
def status():
    return link.status()


@router.post("/phone/pair", dependencies=native)
def pair():
    return _run(link.begin_pairing)


@router.post("/phone/pair/cancel", dependencies=native)
def cancel_pair():
    return _run(link.cancel_pairing)


@router.post("/phone/finish", dependencies=native)
def finish():
    return _run(link.finish_setup)


@router.post("/phone/enabled", dependencies=native)
def set_enabled(body: Enabled):
    return _run(lambda: link.set_enabled(body.enabled))


@router.post("/phone/restarted", dependencies=native)
def restarted():
    return _run(link.gateway_restarted)


@router.post("/phone/disconnect", dependencies=native)
def disconnect():
    return _run(link.disconnect)
