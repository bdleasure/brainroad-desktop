"""Phone link behavior against a fake BrainRoad service and a fake local Webapp.

Needs the libraries Hermes ships (websockets, httpx) plus aiohttp for the fake service:
    pip install websockets==15.0.1 httpx==0.28.1 aiohttp
"""
import asyncio
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
try:
    import aiohttp  # noqa: F401
    from aiohttp import web
    import httpx  # noqa: F401
    import websockets  # noqa: F401
    DEPENDENCIES = True
except ImportError:
    DEPENDENCIES = False


def load_phone_link():
    spec = importlib.util.spec_from_file_location("phone_link_under_test", ROOT / "dashboard/phone_link.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def wait_for(predicate, timeout=15.0, message="condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {message}")


class FakeService:
    """Just enough of BrainRoad's device API, run on its own event-loop thread."""

    def __init__(self):
        self.credential_hash = None
        self.polls = 0
        self.revoked_headers = []
        self.control = None
        self.control_closed = threading.Event()
        self.close_with = None
        self.streams = {}
        self.stream_ready = threading.Event()
        self.connects = 0
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(10)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        app = web.Application()
        app.router.add_post("/api/devices/pair", self.pair)
        app.router.add_post("/api/devices/pair/poll", self.poll)
        app.router.add_post("/api/devices/revoke", self.revoke)
        app.router.add_get("/api/devices/connect", self.connect)
        app.router.add_get("/api/devices/stream", self.stream)
        self.runner = web.AppRunner(app)
        self.loop.run_until_complete(self.runner.setup())
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        self.loop.run_until_complete(site.start())
        self.port = site._server.sockets[0].getsockname()[1]
        self.ready.set()
        self.loop.run_forever()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def authorized(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer dev-1."):
            return False
        secret = header.split(".", 1)[1]
        return hashlib.sha256(secret.encode()).hexdigest() == self.credential_hash

    async def pair(self, request):
        body = await request.json()
        self.credential_hash = body["credentialHash"]
        self.pair_body = body
        return web.json_response({"deviceCode": "device-code", "userCode": "ABCD-EFGH",
                                  "verificationUri": f"{self.url}/devices/pair?code=ABCD-EFGH",
                                  "interval": 0.05, "expiresIn": 60})

    async def poll(self, request):
        body = await request.json()
        assert body["deviceCode"] == "device-code"
        self.polls += 1
        if self.polls < 2:
            return web.json_response({"status": "pending"}, status=202)
        return web.json_response({
            "status": "approved", "deviceId": "dev-1", "name": "Test PC", "account": "o***@example.com",
            "publicUrl": "https://app.brainroad.com/computers/dev-1/agent",
            "openUrl": "https://app.brainroad.com/computers/dev-1/",
            "oidc": {"issuer": "https://app.brainroad.com/oidc", "clientId": "device-dev-1",
                     "scopes": "openid profile email"}})

    async def revoke(self, request):
        self.revoked_headers.append(request.headers.get("Authorization"))
        return web.Response(status=204)

    async def connect(self, request):
        if not self.authorized(request):
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connects += 1
        self.control = ws
        self.control_closed.clear()
        self.hello = json.loads((await ws.receive()).data)
        if self.close_with:
            await ws.close(code=self.close_with)
        async for _ in ws:
            pass
        self.control_closed.set()
        return ws

    async def stream(self, request):
        if not self.authorized(request):
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.streams[request.query["id"]] = ws
        self.stream_ready.set()
        self.stream_echo = []
        async for message in ws:
            self.stream_echo.append(message.data)
        return ws

    def call(self, coro, timeout=10):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self):
        async def shutdown():
            for ws in [*self.streams.values(), *([self.control] if self.control else [])]:
                await ws.close()
            await self.runner.cleanup()
        self.call(shutdown(), timeout=20)
        self.loop.call_soon_threadsafe(self.loop.stop)


class EchoWebapp:
    """A loopback TCP server standing in for the Hermes Webapp listener."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()

        async def echo(reader, writer):
            while data := await reader.read(1024):
                writer.write(data)
                await writer.drain()
            writer.close()

        def run():
            asyncio.set_event_loop(self.loop)
            self.server = self.loop.run_until_complete(asyncio.start_server(echo, "127.0.0.1", 0))
            self.port = self.server.sockets[0].getsockname()[1]
            ready.set()
            self.loop.run_forever()

        threading.Thread(target=run, daemon=True).start()
        ready.wait(10)


@unittest.skipUnless(DEPENDENCIES, "needs websockets, httpx and aiohttp")
class PhoneLinkTests(unittest.TestCase):
    def setUp(self):
        self.module = load_phone_link()
        self.service = FakeService()
        self.webapp = EchoWebapp()
        self.temp = tempfile.TemporaryDirectory()
        os.environ["BRAINROAD_URL"] = self.service.url
        self.config = {"webapp": {"enabled": True, "port": self.webapp.port, "host": "127.0.0.1"},
                       "plugins": {"enabled": ["brainroad"]}}
        self.writes = []
        self.link = self.module.PhoneLink(Path(self.temp.name), read_config=lambda: self.config,
                                          write_config=self.write_config)
        self.link.build_webapp = lambda: None
        self.link.start()

    def tearDown(self):
        os.environ.pop("BRAINROAD_URL", None)
        with contextlib.suppress(Exception):
            self.link.set_enabled(False)
        self.service.stop()
        self.temp.cleanup()

    def write_config(self, key, value):
        self.writes.append((key, value))
        section, _, rest = key.partition(".")
        node = self.config.setdefault(section, {})
        parts = rest.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = {"true": True, "false": False}.get(value, value)

    def pair(self):
        status = self.link.begin_pairing()
        self.assertEqual(status["pairing"]["code"], "ABCD-EFGH")
        self.assertNotIn("secret", json.dumps(status))
        wait_for(lambda: self.link.status()["state"] == "connected", message="connected")

    def test_pairing_configures_hermes_and_relays_to_loopback(self):
        self.config["webapp"]["port"] = self.webapp.port
        self.pair()
        saved = json.loads(self.link.state_path.read_text())
        self.assertEqual(hashlib.sha256(saved["secret"].encode()).hexdigest(), self.service.credential_hash)
        if os.name == "posix":
            self.assertEqual(self.link.state_path.stat().st_mode & 0o777, 0o600)
        self.assertIn(("webapp.public_url", "https://app.brainroad.com/computers/dev-1/agent"), self.writes)
        self.assertIn(("dashboard.oauth.self_hosted.client_id", "device-dev-1"), self.writes)
        self.assertIn(("webapp.host", "127.0.0.1"), self.writes)
        self.assertNotIn("secret", json.dumps(self.service.pair_body).lower().replace("credentialhash", ""))
        self.assertTrue(self.service.hello["webapp"]["ready"])

        self.service.call(self.service.control.send_str(json.dumps({"type": "open", "stream": "stream-0123456789abcdef"})))
        self.assertTrue(self.service.stream_ready.wait(10))
        self.service.call(self.service.streams["stream-0123456789abcdef"].send_bytes(b"GET / HTTP/1.1\r\n\r\n"))
        wait_for(lambda: self.service.stream_echo, message="echo through relay")
        self.assertEqual(self.service.stream_echo[0], b"GET / HTTP/1.1\r\n\r\n")

        self.link.set_enabled(False)
        self.assertTrue(self.service.control_closed.wait(10), "turning off closes the connection")
        wait_for(lambda: self.link.status()["state"] == "paused", message="paused")
        connects = self.service.connects
        time.sleep(1.5)
        self.assertEqual(self.service.connects, connects, "no reconnect while turned off")

    def test_revocation_by_brainroad_stops_reconnecting(self):
        self.service.close_with = 4401
        status = self.link.begin_pairing()
        self.assertEqual(status["state"], "pairing")
        wait_for(lambda: self.link.status()["state"] == "revoked", message="revoked")
        self.assertFalse(self.link.status()["enabled"])
        connects = self.service.connects
        time.sleep(1.5)
        self.assertEqual(self.service.connects, connects)

    def test_disconnect_revokes_forgets_and_restores_settings(self):
        self.config["webapp"] = {"enabled": False, "port": self.webapp.port}
        self.link.begin_pairing()
        wait_for(lambda: self.link.status()["paired"], message="paired")
        secret = json.loads(self.link.state_path.read_text())["secret"]
        self.writes.clear()
        status = self.link.disconnect()
        self.assertFalse(status["paired"])
        self.assertFalse(self.link.state_path.exists())
        self.assertEqual(self.service.revoked_headers, [f"Bearer dev-1.{secret}"])
        self.assertIn(("webapp.enabled", "false"), self.writes)
        self.assertIn(("webapp.public_url", None), self.writes)
        self.assertIn(("dashboard.oauth.self_hosted.issuer", None), self.writes)

    def test_existing_web_access_address_is_not_replaced(self):
        self.config["webapp"]["public_url"] = "https://hermes.example.net"
        with self.assertRaises(self.module.PhoneLinkError):
            self.link.begin_pairing()
        self.config["webapp"] = {"enabled": True, "host": "0.0.0.0"}
        with self.assertRaises(self.module.PhoneLinkError):
            self.link.begin_pairing()
        self.assertEqual(self.writes, [])

    def test_service_address_must_be_https_except_loopback(self):
        os.environ["BRAINROAD_URL"] = "http://brainroad.example.com"
        with self.assertRaises(self.module.PhoneLinkError):
            self.module.service_url()
        os.environ["BRAINROAD_URL"] = "https://app.brainroad.com/"
        self.assertEqual(self.module.service_url(), "https://app.brainroad.com")
        self.assertEqual(self.module.websocket_url("https://app.brainroad.com", "/x"), "wss://app.brainroad.com/x")


if __name__ == "__main__":
    unittest.main()
