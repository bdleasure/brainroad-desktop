"""BrainRoad phone link: reach this computer's Hermes Webapp from the owner's phone.

Pairing follows the device-authorization pattern: this computer creates its own secret,
sends BrainRoad only its SHA-256 hash, and shows a short code that the owner approves while
signed in to BrainRoad. After approval this module keeps ONE outbound WebSocket to BrainRoad.
For each request the owner's phone makes, BrainRoad asks for a stream; this module opens a
second outbound WebSocket and pipes it to the Webapp on 127.0.0.1. Nothing on this computer
listens on the network, and the Webapp keeps its own sign-in (BrainRoad's per-computer OIDC
client) in front of everything that is relayed.

Turning the link off closes the connection at once. Disconnecting also forgets the secret,
asks BrainRoad to revoke the computer, and restores the Webapp settings found before pairing.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import platform
import random
import re
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

logger = logging.getLogger("brainroad.phone_link")

VERSION = "0.3.1"
DEFAULT_SERVICE = "https://app.brainroad.com"
STATE_FILE = "phone-link.json"
LOCK_FILE = "phone-link.lock"
# Webapp settings that pairing changes and disconnecting restores.
MANAGED_KEYS = (
    "webapp.enabled", "webapp.host", "webapp.public_url",
    "dashboard.oauth.self_hosted.issuer", "dashboard.oauth.self_hosted.client_id",
    "dashboard.oauth.self_hosted.scopes",
)
REVOKED_CLOSE_CODES = {4401, 4403}
STREAM_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")
_INSTANCES: dict = {}


class PhoneLinkError(RuntimeError):
    """A user-facing reason the phone link cannot do what was asked."""


def service_url() -> str:
    """BrainRoad's address. ``BRAINROAD_URL`` exists for tests; anything other than https is
    accepted only on loopback so a typo cannot send the credential in clear text."""
    raw = (os.environ.get("BRAINROAD_URL") or DEFAULT_SERVICE).strip().rstrip("/")
    parts = urlsplit(raw)
    loopback = parts.hostname in {"127.0.0.1", "localhost", "::1"}
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise PhoneLinkError("BRAINROAD_URL must be an https:// address.")
    return raw


def websocket_url(base: str, path: str) -> str:
    return ("wss://" + base[len("https://"):] if base.startswith("https://")
            else "ws://" + base[len("http://"):]) + path


def credential_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def computer_description() -> dict[str, str]:
    system = platform.system()
    name = {"Windows": "windows", "Darwin": "macos"}.get(system, "linux")
    release = platform.mac_ver()[0] if system == "Darwin" else platform.release()
    return {"name": (platform.node() or "This computer")[:64], "platform": name,
            "os": f"{system} {release}".strip(), "arch": platform.machine()}


def hermes_version() -> str:
    """Hermes's own version string; a git install's package metadata says 0.0.0."""
    try:
        from hermes_cli import __version__
        if __version__ and __version__ != "0.0.0":
            return str(__version__)
    except Exception:
        pass
    from importlib.metadata import PackageNotFoundError, version
    try:
        found = version("hermes-agent")
    except PackageNotFoundError:
        return ""
    return "" if found == "0.0.0" else found


def webapp_supported() -> bool:
    """Hermes' gateway-served browser workspace (the Webapp) is what the phone opens. Hermes
    0.22.5 and earlier releases do not have it; it exists on Hermes' main channel."""
    import importlib.util
    try:
        return importlib.util.find_spec("gateway.webapp_listener") is not None
    except (ImportError, ValueError):
        return False


def write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


class ProcessLock:
    """Held for the life of the process so only one connector runs per Hermes home."""

    def __init__(self, path: Path):
        self.path, self.handle = path, None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True


def hermes_config_writer(home: Path) -> Callable[[str, Optional[str]], None]:
    """Change one setting through Hermes' own ``hermes config set``/``unset`` so its validation,
    locking and managed-scope rules apply. ``None`` removes the setting."""
    def write(key: str, value: Optional[str]) -> None:
        args = ["config", "unset", key] if value is None else ["config", "set", key, value]
        result = subprocess.run(
            [sys.executable, "-m", "hermes_cli.main", *args], capture_output=True, text=True,
            timeout=120, env={**os.environ, "HERMES_HOME": str(home)},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0 and value is not None:
            raise PhoneLinkError(f"Hermes refused to change {key}: "
                                 f"{(result.stderr or result.stdout).strip()[-300:]}")
    return write


def read_setting(config: dict, dotted: str) -> Any:
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@dataclass
class Pairing:
    device_code: str
    secret: str
    user_code: str
    verification_uri: str
    expires_at: float
    interval: float
    status: str = "waiting"   # waiting | approved | expired | denied | failed
    error: str = ""


@dataclass
class LinkStatus:
    state: str = "off"        # off | pairing | connecting | connected | paused | revoked | error
    detail: str = ""
    since: float = field(default_factory=time.time)
    streams: int = 0


class PhoneLink:
    """Pairing, settings and the outbound relay for one Hermes home."""

    def __init__(self, home: Path, *, read_config: Callable[[], dict],
                 write_config: Optional[Callable[[str, Optional[str]], None]] = None,
                 plugin_enabled: Callable[[], bool] = lambda: True,
                 notify: Callable[[dict], None] = lambda _status: None):
        self.home = Path(home)
        self.data_dir = self.home / "plugin-data" / "brainroad"
        self.read_config = read_config
        self.write_config = write_config or hermes_config_writer(self.home)
        self.plugin_enabled = plugin_enabled
        self.notify = notify
        self.pairing: Optional[Pairing] = None
        self.link = LinkStatus()
        self._lock = threading.RLock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._run_task: Optional[asyncio.Future] = None
        self._wake: Optional[asyncio.Event] = None
        self._process_lock = ProcessLock(self.data_dir / LOCK_FILE)
        self._owns_lock = False

    # ----- persisted state -------------------------------------------------------------
    @property
    def state_path(self) -> Path:
        return self.data_dir / STATE_FILE

    def saved(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        write_private(self.state_path, data)

    # ----- status ----------------------------------------------------------------------
    def status(self) -> dict:
        saved = self.saved()
        config = self._safe_config()
        pairing = self.pairing
        try:
            service = service_url()
        except PhoneLinkError as exc:
            service = str(exc)
        out = {
            "version": VERSION, "computer": computer_description(), "hermes": hermes_version(),
            "service": service, "paired": bool(saved.get("device_id")),
            "enabled": bool(saved.get("enabled")),
            "setupComplete": bool(saved.get("setup_complete")), "setupError": saved.get("setup_error", ""),
            "state": self.link.state, "detail": self.link.detail, "since": self.link.since,
            "streams": self.link.streams, "deviceName": saved.get("name"),
            "account": saved.get("account"), "openUrl": saved.get("open_url"),
            "webapp": {"enabled": bool(read_setting(config, "webapp.enabled")),
                       "publicUrl": read_setting(config, "webapp.public_url") or ""},
            "restartNeeded": bool(saved.get("restart_needed")),
            "connectorHere": self._owns_lock, "webappSupported": webapp_supported(),
        }
        if pairing and pairing.status in {"waiting", "failed", "expired", "denied"}:
            out["pairing"] = {"status": pairing.status, "code": pairing.user_code,
                              "url": pairing.verification_uri, "expiresAt": pairing.expires_at,
                              "error": pairing.error}
        return out

    def _safe_config(self) -> dict:
        try:
            config = self.read_config()
        except Exception:
            return {}
        return config if isinstance(config, dict) else {}

    def _set_link(self, state: str, detail: str = "") -> None:
        if (state, detail) != (self.link.state, self.link.detail):
            self.link = LinkStatus(state=state, detail=detail, streams=self.link.streams)
            with contextlib.suppress(Exception):
                self.notify(self.status())

    # ----- background loop -------------------------------------------------------------
    def start(self) -> bool:
        """Start the background loop once per process; only the process holding the home's lock
        runs the relay, so a second Hermes process for the same home stays passive."""
        with self._lock:
            if self._thread is not None:
                return self._owns_lock
            self._owns_lock = self._process_lock.acquire()
            self._loop = asyncio.new_event_loop()
            ready = threading.Event()

            def run() -> None:
                asyncio.set_event_loop(self._loop)
                self._wake = asyncio.Event()
                ready.set()
                self._loop.run_until_complete(self._supervise())

            self._thread = threading.Thread(target=run, name="brainroad-phone-link", daemon=True)
            self._thread.start()
            ready.wait(5)
            return self._owns_lock

    def _call(self, coro) -> Any:
        if self._loop is None:
            self.start()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=60)

    def poke(self) -> None:
        if self._loop is not None and self._wake is not None:
            self._loop.call_soon_threadsafe(self._wake.set)

    async def _supervise(self) -> None:
        delay = 1.0
        while True:
            if not self._owns_lock:
                self._owns_lock = self._process_lock.acquire()
            saved = self.saved()
            ready = saved.get("device_id") and saved.get("setup_complete") and saved.get("enabled")
            if self._owns_lock and ready and self.plugin_enabled():
                started = time.monotonic()
                outcome = await self._connect_once(saved)
                if outcome == "revoked":
                    self._mark_revoked()
                    continue
                delay = 1.0 if time.monotonic() - started > 60 else min(delay * 2, 60.0)
                await self._sleep(delay * (0.75 + random.random() / 2))
                continue
            if not saved.get("device_id"):
                self._set_link("pairing" if self.pairing and self.pairing.status == "waiting" else "off")
            elif self.link.state != "revoked":
                self._set_link("paused" if not saved.get("enabled") else "off",
                               "" if self._owns_lock else "Another Hermes process is relaying.")
            await self._sleep(10)

    async def _sleep(self, seconds: float) -> None:
        assert self._wake is not None
        self._wake.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)

    def _mark_revoked(self) -> None:
        saved = self.saved()
        if saved:
            saved["enabled"] = False
            self._save(saved)
        self._set_link("revoked", "BrainRoad no longer accepts this computer. Disconnect it here, "
                                  "then connect it again if you still want phone access.")

    def _auth_headers(self, saved: dict) -> dict:
        return {"Authorization": f"Bearer {saved['device_id']}.{saved['secret']}",
                "X-BrainRoad-Plugin": VERSION}

    def _webapp_port(self) -> Optional[int]:
        config = self._safe_config()
        if read_setting(config, "webapp.enabled") is not True:
            return None
        port = read_setting(config, "webapp.port")
        return int(port) if isinstance(port, int) and 0 < port < 65536 else 9120

    async def _connect_once(self, saved: dict) -> str:
        import websockets
        from websockets.exceptions import ConnectionClosed, InvalidStatus

        base = service_url()
        self._set_link("connecting")
        try:
            async with websockets.connect(
                websocket_url(base, "/api/devices/connect"), additional_headers=self._auth_headers(saved),
                ping_interval=20, ping_timeout=20, open_timeout=20, max_size=64 * 1024,
            ) as control:
                port = self._webapp_port()
                await control.send(json.dumps({
                    "type": "hello", "plugin": VERSION, "hermes": hermes_version(),
                    "computer": computer_description(), "webapp": {"ready": port is not None},
                }))
                self._set_link("connected" if port else "error",
                               "" if port else "Hermes Web Access is off on this computer.")
                watcher = asyncio.ensure_future(self._watch_enabled(control))
                try:
                    async for raw in control:
                        message = json.loads(raw) if isinstance(raw, str) else {}
                        stream = message.get("stream") if message.get("type") == "open" else None
                        if isinstance(stream, str) and STREAM_ID.fullmatch(stream):
                            asyncio.ensure_future(self._relay(base, saved, stream))
                        elif message.get("type") == "revoked":
                            return "revoked"
                finally:
                    watcher.cancel()
                code = control.close_code
        except InvalidStatus as exc:
            status = exc.response.status_code
            if status in (401, 403):
                return "revoked"
            self._set_link("error", f"BrainRoad answered {status}. Retrying.")
            return "retry"
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else None
        except (OSError, asyncio.TimeoutError) as exc:
            self._set_link("error", f"Cannot reach BrainRoad ({exc.__class__.__name__}). Retrying.")
            return "retry"
        if code in REVOKED_CLOSE_CODES:
            return "revoked"
        if not self.saved().get("enabled"):
            self._set_link("paused")
            return "stopped"
        self._set_link("connecting", "Reconnecting.")
        return "retry"

    async def _watch_enabled(self, control) -> None:
        """Close the relay promptly when the person turns it off here or disables the plugin."""
        while True:
            await self._sleep(5)
            if not self.saved().get("enabled") or not self.plugin_enabled():
                await control.close(1000, "turned off on this computer")
                return

    async def _relay(self, base: str, saved: dict, stream_id: str) -> None:
        import websockets

        port = self._webapp_port()
        if port is None:
            return
        try:
            async with websockets.connect(
                websocket_url(base, f"/api/devices/stream?id={stream_id}"),
                additional_headers=self._auth_headers(saved), ping_interval=None,
                open_timeout=15, max_size=None, compression=None,
            ) as upstream:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                self.link.streams += 1
                try:
                    await _pipe(upstream, reader, writer)
                finally:
                    self.link.streams -= 1
                    writer.close()
                    with contextlib.suppress(Exception):
                        await writer.wait_closed()
        except Exception as exc:  # one failed request must not stop the relay
            logger.debug("BrainRoad stream %s ended: %s", stream_id[:8], exc.__class__.__name__)

    # ----- pairing ---------------------------------------------------------------------
    def begin_pairing(self) -> dict:
        if not webapp_supported():
            raise PhoneLinkError("Phone access needs a newer Hermes with its browser workspace. "
                                 "Hermes 0.22.5 does not include it yet.")
        if self.saved().get("device_id"):
            raise PhoneLinkError("This computer is already connected. Disconnect it first.")
        conflict = self._webapp_conflict()
        if conflict:
            raise PhoneLinkError(conflict)
        return self._call(self._begin_pairing())

    def _webapp_conflict(self) -> str:
        config = self._safe_config()
        url = read_setting(config, "webapp.public_url") or ""
        host = read_setting(config, "webapp.host") or "127.0.0.1"
        ours = url.startswith(service_url() + "/computers/")
        if url and not ours:
            return ("Hermes Web Access already uses its own address on this computer. Turn it off in "
                    "Hermes Settings, Web Access, then connect BrainRoad.")
        if host not in {"127.0.0.1", "::1", "localhost"} and read_setting(config, "webapp.enabled"):
            return ("Hermes Web Access is open to this network. Turn it off in Hermes Settings, "
                    "Web Access, then connect BrainRoad.")
        return ""

    async def _begin_pairing(self) -> dict:
        import httpx

        secret = secrets.token_urlsafe(32)
        body = {**computer_description(), "credentialHash": credential_hash(secret),
                "plugin": VERSION, "hermes": hermes_version()}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{service_url()}/api/devices/pair", json=body)
        if response.status_code != 200:
            raise PhoneLinkError(_service_error(response, "BrainRoad could not start pairing."))
        data = response.json()
        self.pairing = Pairing(
            device_code=data["deviceCode"], secret=secret, user_code=data["userCode"],
            verification_uri=data["verificationUri"], interval=float(data.get("interval", 3)),
            expires_at=time.time() + float(data.get("expiresIn", 600)))
        self._set_link("pairing")
        asyncio.ensure_future(self._poll_pairing(self.pairing))
        return self.status()

    async def _poll_pairing(self, pairing: Pairing) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            while pairing is self.pairing and pairing.status == "waiting":
                if time.time() > pairing.expires_at:
                    pairing.status = "expired"
                    break
                await asyncio.sleep(pairing.interval)
                try:
                    response = await client.post(f"{service_url()}/api/devices/pair/poll",
                                                 json={"deviceCode": pairing.device_code})
                except httpx.HTTPError:
                    continue
                if response.status_code == 202:
                    continue
                if response.status_code == 200:
                    # A local setup failure is kept as setup_error; Finish setup retries it.
                    with contextlib.suppress(PhoneLinkError):
                        await asyncio.to_thread(self._complete_pairing, pairing, response.json())
                    pairing.status = "approved"
                    break
                pairing.status = {410: "expired", 403: "denied"}.get(response.status_code, "failed")
                pairing.error = _service_error(response, "")
        self._set_link(self.link.state if pairing.status == "approved" else "off")
        self.poke()

    def _complete_pairing(self, pairing: Pairing, data: dict) -> None:
        # Keep the credential first: a failed local step below can be retried with Finish setup.
        config = self._safe_config()
        self._save({"device_id": data["deviceId"], "secret": pairing.secret, "name": data.get("name"),
                    "account": data.get("account"), "open_url": data.get("openUrl"),
                    "public_url": data["publicUrl"], "oidc": data["oidc"], "enabled": True,
                    "paired_at": time.time(), "restart_needed": True, "setup_complete": False,
                    "previous": {key: read_setting(config, key) for key in MANAGED_KEYS}})
        self.finish_setup()

    def finish_setup(self) -> dict:
        """Build the Webapp bundle if needed and point the Webapp's sign-in at this computer's
        BrainRoad client, exactly as Hermes' own Web Access does for an own HTTPS address."""
        saved = self.saved()
        if not saved.get("device_id"):
            raise PhoneLinkError("This computer is not connected to BrainRoad.")
        try:
            self.build_webapp()
            oidc = saved["oidc"]
            for key, value in {
                "webapp.enabled": "true", "webapp.host": "127.0.0.1",
                "webapp.public_url": saved["public_url"],
                "dashboard.oauth.self_hosted.issuer": oidc["issuer"],
                "dashboard.oauth.self_hosted.client_id": oidc["clientId"],
                "dashboard.oauth.self_hosted.scopes": oidc.get("scopes", "openid profile email"),
            }.items():
                self.write_config(key, value)
        except PhoneLinkError as exc:
            saved["setup_error"] = str(exc)
            self._save(saved)
            raise
        saved.update(setup_complete=True, setup_error="", restart_needed=True)
        self._save(saved)
        self.poke()
        return self.status()

    def build_webapp(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "hermes_cli.main", "webapp", "--build-only"], capture_output=True,
            text=True, timeout=1800, env={**os.environ, "HERMES_HOME": str(self.home)},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            raise PhoneLinkError("Hermes could not prepare its browser workspace: "
                                 + (result.stderr or result.stdout).strip()[-300:])

    def cancel_pairing(self) -> dict:
        self.pairing = None
        self._set_link("off")
        return self.status()

    # ----- local controls --------------------------------------------------------------
    def set_enabled(self, enabled: bool) -> dict:
        saved = self.saved()
        if not saved.get("device_id"):
            raise PhoneLinkError("This computer is not connected to BrainRoad.")
        saved["enabled"] = enabled
        self._save(saved)
        self._set_link("connecting" if enabled else "paused")
        self.poke()
        return self.status()

    def gateway_restarted(self) -> dict:
        saved = self.saved()
        if saved.get("restart_needed"):
            saved["restart_needed"] = False
            self._save(saved)
        return self.status()

    def disconnect(self) -> dict:
        """Forget this computer's BrainRoad credential and restore the earlier Web Access
        settings. Revocation at BrainRoad is attempted but not required to stop local access."""
        saved = self.saved()
        if not saved.get("device_id"):
            return self.status()
        saved["enabled"] = False
        self._save(saved)
        self.poke()
        with contextlib.suppress(Exception):
            self._call(self._revoke(saved))
        for key, value in (saved.get("previous") or {}).items():
            if key in MANAGED_KEYS:
                self.write_config(key, None if value is None else _cli_value(value))
        with contextlib.suppress(OSError):
            self.state_path.unlink()
        self.pairing = None
        self._set_link("off", "Disconnected. Restart Hermes' gateway to finish turning off Web Access.")
        return {**self.status(), "restartNeeded": True}

    async def _revoke(self, saved: dict) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(f"{service_url()}/api/devices/revoke", headers=self._auth_headers(saved))


def link_for(home: Path, **options) -> PhoneLink:
    """One PhoneLink per Hermes home in this process, even if Hermes imports the backend twice."""
    key = str(Path(home).resolve())
    if key not in _INSTANCES:
        _INSTANCES[key] = PhoneLink(Path(home), **options)
    return _INSTANCES[key]


async def _pipe(upstream, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy bytes both ways until either side finishes."""
    async def to_local() -> None:
        async for chunk in upstream:
            if isinstance(chunk, str):
                chunk = chunk.encode()
            writer.write(chunk)
            await writer.drain()
        with contextlib.suppress(OSError):
            writer.write_eof()

    async def to_service() -> None:
        while True:
            chunk = await reader.read(64 * 1024)
            if not chunk:
                break
            await upstream.send(chunk)
        await upstream.close()

    tasks = [asyncio.ensure_future(to_local()), asyncio.ensure_future(to_service())]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in done:
        with contextlib.suppress(Exception):
            task.result()
    if pending:
        await asyncio.wait(pending, timeout=5)
    for task in pending:
        task.cancel()


def _service_error(response, fallback: str) -> str:
    with contextlib.suppress(Exception):
        message = response.json().get("error")
        if isinstance(message, str) and message:
            return message[:300]
    return fallback or f"BrainRoad answered {response.status_code}."


def _cli_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
