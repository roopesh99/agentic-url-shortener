"""Smoke gate: build the real artifact, start it, and exercise it over HTTP. Tests run in-process;
this proves the packaged service starts and answers like its contract says. The server is always
stopped, and its data lives in a temporary directory."""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..engine.models import GateResult
from .base import Gate, GateContext
from .builtin import _failure_excerpt


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a 302 is a result to check, not to follow
        return None


_HTTP = urllib.request.build_opener(_NoRedirect)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _fill(value: Any, saved: dict[str, str]) -> Any:
    if isinstance(value, str):
        for k, v in saved.items():
            value = value.replace("{" + k + "}", v)
        return value
    if isinstance(value, dict):
        return {k: _fill(v, saved) for k, v in value.items()}
    return value


def _request(base: str, step: dict, saved: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    body = step.get("json")
    data = None if body is None else (body if isinstance(body, str) else json.dumps(_fill(body, saved))).encode()
    req = urllib.request.Request(base + _fill(step["path"], saved), data=data, method=step.get("method", "GET"))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in _fill(step.get("headers", {}), saved).items():
        req.add_header(k, v)
    try:
        with _HTTP.open(req, timeout=10) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def run_step(base: str, mgmt: str, step: dict, saved: dict[str, str]) -> str | None:
    """None if the step behaves as expected, otherwise what was wrong."""
    status, headers, raw = _request(mgmt if step.get("port") == "management" else base, step, saved)
    if status != step["expect"]:
        return f"status {status}, expected {step['expect']}: {raw[:200].decode(errors='replace')}"
    for name, want in _fill(step.get("expect_headers", {}), saved).items():
        got = headers.get(name.lower())
        if got is None or (want != "*" and want not in got):
            return f"header {name}: {got!r}, expected {'present' if want == '*' else repr(want)}"
    if "expect_json" in step or "save" in step:
        try:
            doc = json.loads(raw)
        except ValueError:
            return f"body is not JSON: {raw[:200].decode(errors='replace')}"
        for key, want in _fill(step.get("expect_json", {}), saved).items():
            if doc.get(key) != want:
                return f"{key}: {doc.get(key)!r}, expected {want!r}"
        for var, key in step.get("save", {}).items():
            saved[var] = str(doc[key])
    return None


class ServiceSmokeGate(Gate):
    """args: project; steps (list of {name, method, path, json, headers, port, expect, expect_headers,
    expect_json, save}); health (default /health); startup_seconds (default 90)."""

    name = "service_smoke"

    async def check(self, ctx: GateContext) -> GateResult:
        mvn, java = shutil.which("mvn"), shutil.which("java")
        if not mvn or not java:
            return self.result(False, "mvn and java are needed on PATH")
        project = ctx.workspace / self.args.get("project", ".")
        build = await asyncio.create_subprocess_exec(
            mvn, "-B", "-q", "--no-transfer-progress", "-Dmaven.test.skip=true", "package", cwd=project,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await build.communicate()
        jars = [j for j in (project / "target").glob("*.jar") if not j.name.endswith(("-plain.jar", ".original"))]
        if build.returncode != 0 or len(jars) != 1:
            return self.result(False, f"packaging failed or no single jar ({[j.name for j in jars]})\n"
                               + _failure_excerpt(out.decode(errors="replace")))
        return await asyncio.to_thread(self._exercise, jars[0])

    def _exercise(self, jar: Path) -> GateResult:
        import subprocess

        port, mgmt_port = _free_port(), _free_port()
        base, mgmt = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{mgmt_port}"
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryFile() as log:
            server = subprocess.Popen(
                ["java", "-jar", str(jar), f"--server.port={port}", f"--management.server.port={mgmt_port}",
                 f"--shortener.data-dir={data}"], stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + self.args.get("startup_seconds", 90)
                while True:
                    if server.poll() is not None:
                        return self.result(False, "the service exited during startup\n" + self._tail(log))
                    try:
                        if _request(base, {"path": self.args.get("health", "/health")}, {})[0] == 200:
                            break
                    except OSError:
                        pass
                    if time.monotonic() > deadline:
                        return self.result(False, "the service did not become healthy in time\n" + self._tail(log))
                    time.sleep(0.5)
                started = time.monotonic() - (deadline - self.args.get("startup_seconds", 90))
                saved: dict[str, str] = {}
                passed = []
                for step in self.args.get("steps", []):
                    problem = run_step(base, mgmt, step, saved)
                    if problem:
                        return self.result(False, f"step '{step['name']}' failed: {problem} "
                                                  f"(passed before it: {passed})\n" + self._tail(log))
                    passed.append(step["name"])
                return self.result(True, f"packaged service started in {started:.1f}s and passed {len(passed)} "
                                         f"HTTP step(s): {', '.join(passed)}")
            finally:
                server.terminate()
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    server.kill()

    @staticmethod
    def _tail(log) -> str:
        log.seek(0)
        return "\n".join(log.read().decode(errors="replace").splitlines()[-25:])
