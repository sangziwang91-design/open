import http.client
import json
import threading
import time
from pathlib import Path

import pytest

from agentbridge.bridge.controller import BridgeConfig, BridgeController
from agentbridge.bridge.server import create_server
from agentbridge.persistence.database import Database
from tests.test_bridge_protocol import browser_task

TOKEN = "t" * 48
EXTENSION_ORIGIN = "chrome-extension://abcdefghijklmnop"


@pytest.fixture
def live_bridge(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    controller = BridgeController(
        BridgeConfig(
            workspace=workspace,
            database=Database(tmp_path / "bridge.db"),
            runs_dir=tmp_path / "runs",
            executor_name="fake",
        )
    )
    controller.start()
    server = create_server("127.0.0.1", 0, controller, TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        controller.stop()
        thread.join(timeout=5)


def request(
    port: int,
    method: str,
    path: str,
    payload=None,
    *,
    token: str | None = TOKEN,
    origin: str | None = EXTENSION_ORIGIN,
    headers: dict[str, str] | None = None,
):
    body = json.dumps(payload).encode() if payload is not None else None
    request_headers = dict(headers or {})
    if payload is not None:
        request_headers.setdefault("Content-Type", "application/json")
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        request_headers["Origin"] = origin
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=body, headers=request_headers)
    response = connection.getresponse()
    data = response.read()
    result = json.loads(data) if data else None
    response_headers = dict(response.getheaders())
    connection.close()
    return response.status, result, response_headers


def wait_http_job(port: int, job_id: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status, job, _ = request(port, "GET", f"/v1/jobs/{job_id}")
        assert status == 200
        if job["status"] in {"FINISHED", "ERROR"}:
            return job
        time.sleep(0.02)
    raise AssertionError("HTTP bridge job did not finish")


def test_health_requires_bearer_token(live_bridge: int) -> None:
    status, _, _ = request(live_bridge, "GET", "/health", token=None)
    assert status == 401
    status, body, _ = request(live_bridge, "GET", "/health")
    assert status == 200
    assert body == {"status": "READY", "protocol": "agentbridge/1"}


def test_extension_preflight_is_bounded(live_bridge: int) -> None:
    status, _, headers = request(
        live_bridge,
        "OPTIONS",
        "/v1/jobs",
        token=None,
        headers={"Access-Control-Request-Private-Network": "true"},
    )
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == EXTENSION_ORIGIN
    assert headers["Access-Control-Allow-Private-Network"] == "true"


def test_web_page_origin_is_rejected_even_with_token(live_bridge: int) -> None:
    status, body, _ = request(
        live_bridge,
        "GET",
        "/health",
        origin="https://chatgpt.com",
    )
    assert status == 403
    assert body["error"] == "origin_not_allowed"


def test_dns_rebinding_host_header_is_rejected(live_bridge: int) -> None:
    status, body, _ = request(
        live_bridge,
        "GET",
        "/health",
        headers={"Host": "attacker.example"},
    )
    assert status == 403
    assert body["error"] == "loopback_only"


def test_http_job_round_trip_and_idempotency(live_bridge: int) -> None:
    payload = browser_task().model_dump(mode="json")
    status, submitted, _ = request(live_bridge, "POST", "/v1/jobs", payload)
    assert status == 201
    final = wait_http_job(live_bridge, submitted["job_id"])
    assert final["result"]["status"] == "COMPLETED"
    assert final["result"]["checks"][0]["status"] == "PASS"

    status, duplicate, _ = request(live_bridge, "POST", "/v1/jobs", payload)
    assert status == 200
    assert duplicate["job_id"] == submitted["job_id"]

    changed = {**payload, "goal": "different content"}
    status, conflict, _ = request(live_bridge, "POST", "/v1/jobs", changed)
    assert status == 409
    assert conflict["error"] == "request_conflict"


def test_http_rejects_chat_authority_escalation(live_bridge: int) -> None:
    payload = browser_task(request_id="REQ-authority").model_dump(mode="json")
    payload["workspace"] = "C:/private"
    status, body, _ = request(live_bridge, "POST", "/v1/jobs", payload)
    assert status == 422
    assert body["error"] == "invalid_task"


def test_http_rejects_wrong_content_type_and_large_body(live_bridge: int) -> None:
    status, body, _ = request(
        live_bridge,
        "POST",
        "/v1/jobs",
        None,
        headers={"Content-Type": "text/plain", "Content-Length": "1"},
    )
    assert status == 415
    assert body["error"] == "content_type_must_be_application_json"

    status, body, _ = request(
        live_bridge,
        "POST",
        "/v1/jobs",
        None,
        headers={"Content-Type": "application/json", "Content-Length": "65537"},
    )
    assert status == 413
    assert body["error"] == "request_too_large"


def test_server_refuses_non_loopback_bind(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    controller = BridgeController(
        BridgeConfig(
            workspace=workspace,
            database=Database(tmp_path / "bridge.db"),
            runs_dir=tmp_path / "runs",
            executor_name="fake",
        )
    )
    with pytest.raises(ValueError, match="loopback"):
        create_server("0.0.0.0", 8765, controller, TOKEN)
