import hmac
import ipaddress
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from agentbridge.bridge.controller import BridgeController, BridgeQueueFullError
from agentbridge.bridge.protocol import BrainTaskMessage
from agentbridge.bridge.store import BridgeRequestConflictError

MAX_REQUEST_BYTES = 65_536


def _is_loopback_host(value: str) -> bool:
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _host_header_is_loopback(value: str | None) -> bool:
    if not value:
        return False
    try:
        hostname = urlsplit(f"//{value}").hostname
    except ValueError:
        return False
    return bool(hostname and _is_loopback_host(hostname))


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return (
        parsed.scheme == "chrome-extension"
        and bool(parsed.netloc)
        and not parsed.path.strip("/")
        and not parsed.query
        and not parsed.fragment
    )


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        controller: BridgeController,
        token: str,
    ) -> None:
        self.controller = controller
        self.token = token
        super().__init__(address, BridgeRequestHandler)


class BridgeRequestHandler(BaseHTTPRequestHandler):
    server: BridgeHTTPServer
    server_version = "AgentBridge"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def do_OPTIONS(self) -> None:
        if not self._request_boundary_ok(require_auth=False):
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        if self.headers.get("Access-Control-Request-Private-Network") == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._request_boundary_ok():
            return
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {"status": "READY", "protocol": "agentbridge/1"},
            )
            return
        prefix = "/v1/jobs/"
        if path.startswith(prefix):
            job_id = path[len(prefix) :]
            if not job_id or "/" in job_id:
                self._send_error(HTTPStatus.NOT_FOUND, "not_found")
                return
            job = self.server.controller.store.get(job_id)
            if job is None:
                self._send_error(HTTPStatus.NOT_FOUND, "job_not_found")
                return
            self._send_json(HTTPStatus.OK, job.view().model_dump(mode="json"))
            return
        self._send_error(HTTPStatus.NOT_FOUND, "not_found")

    def do_POST(self) -> None:
        if not self._request_boundary_ok():
            return
        if urlsplit(self.path).path != "/v1/jobs":
            self._send_error(HTTPStatus.NOT_FOUND, "not_found")
            return
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if media_type != "application/json":
            self._send_error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "content_type_must_be_application_json",
            )
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_content_length")
            return
        if length < 1 or length > MAX_REQUEST_BYTES:
            self._send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large")
            return
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            task = BrainTaskMessage.model_validate(payload)
            job, created = self.server.controller.submit(task)
        except UnicodeDecodeError:
            self._send_error(HTTPStatus.BAD_REQUEST, "request_must_be_utf8")
            return
        except json.JSONDecodeError:
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_json")
            return
        except ValidationError as exc:
            self._send_json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {
                    "error": "invalid_task",
                    "detail": exc.errors(include_url=False, include_input=False),
                },
            )
            return
        except BridgeRequestConflictError as exc:
            self._send_error(HTTPStatus.CONFLICT, "request_conflict", str(exc))
            return
        except BridgeQueueFullError as exc:
            self._send_error(HTTPStatus.TOO_MANY_REQUESTS, "queue_full", str(exc))
            return
        current = self.server.controller.store.get(job.job_id) or job
        self._send_json(
            HTTPStatus.CREATED if created else HTTPStatus.OK,
            current.view().model_dump(mode="json"),
        )

    def _request_boundary_ok(self, require_auth: bool = True) -> bool:
        try:
            remote_is_loopback = ipaddress.ip_address(
                self.client_address[0]
            ).is_loopback
        except ValueError:
            remote_is_loopback = False
        if not remote_is_loopback or not _host_header_is_loopback(
            self.headers.get("Host")
        ):
            self._send_error(HTTPStatus.FORBIDDEN, "loopback_only")
            return False
        origin = self.headers.get("Origin")
        if not _origin_allowed(origin):
            self._send_error(HTTPStatus.FORBIDDEN, "origin_not_allowed")
            return False
        if require_auth:
            authorization = self.headers.get("Authorization", "")
            expected = f"Bearer {self.server.token}"
            if not hmac.compare_digest(authorization, expected):
                self._send_error(HTTPStatus.UNAUTHORIZED, "unauthorized")
                return False
        return True

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin and _origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(
        self, status: HTTPStatus, error: str, detail: str | None = None
    ) -> None:
        payload = {"error": error}
        if detail:
            payload["detail"] = detail[:1000]
        self._send_json(status, payload)


def create_server(
    host: str,
    port: int,
    controller: BridgeController,
    token: str,
) -> BridgeHTTPServer:
    if not _is_loopback_host(host):
        raise ValueError("bridge host must be a loopback address")
    if port < 0 or port > 65_535:
        raise ValueError("bridge port must be between 0 and 65535")
    return BridgeHTTPServer((host, port), controller, token)


def serve_bridge(
    host: str,
    port: int,
    controller: BridgeController,
    token: str,
) -> None:
    server = create_server(host, port, controller, token)
    recovered = controller.start()
    if recovered:
        print(f"Recovered {recovered} interrupted bridge job(s) as blocked.")
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.shutdown()
        server.server_close()
        controller.stop()
