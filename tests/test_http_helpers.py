from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from api import http


class _Handler:
    def __init__(
        self,
        *,
        path: str = "/",
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        command: str = "GET",
        port: int = 8000,
    ) -> None:
        self.path = path
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.headers = dict(headers or {})
        self.command = command
        self.server = SimpleNamespace(server_port=port)
        self.status: int | None = None
        self.sent_headers: list[tuple[str, str]] = []
        self.ended = False
        self._request_id = "req-1"

    def send_response(self, status: int) -> None:
        self.status = int(status)

    def send_header(self, name: str, value: str) -> None:
        self.sent_headers.append((str(name), str(value)))

    def end_headers(self) -> None:
        self.ended = True


def test_response_helpers_apply_security_headers_and_head_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http, "production_mode", lambda: False)
    handler = _Handler(headers={"Origin": "http://localhost:5173"})
    http.json_response(handler, 201, {"ok": True}, headers={"X-Test": "yes"})
    assert handler.status == 201
    assert handler.ended
    assert handler.wfile.getvalue() == b'{"ok": true}'
    sent = dict(handler.sent_headers)
    assert sent["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert sent["Access-Control-Allow-Credentials"] == "true"
    assert sent["X-Request-ID"] == "req-1"
    assert sent["X-Test"] == "yes"

    head = _Handler(command="HEAD")
    http.text_response(head, 204, "not written")
    assert head.status == 204
    assert head.wfile.getvalue() == b""

    csv_handler = _Handler()
    http.csv_response(csv_handler, "safe.csv", [{"name": "=formula", "n": 2}])
    assert csv_handler.status == 200
    assert b"'=formula" in csv_handler.wfile.getvalue()

    empty_csv = _Handler(command="HEAD")
    http.csv_response(empty_csv, "empty.csv", [])
    assert empty_csv.wfile.getvalue() == b""


def test_parse_json_uses_route_specific_limits_and_rejects_non_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLANORA_MAX_REQUEST_BYTES", "8")
    monkeypatch.setenv("PLANORA_MAX_ANALYTICS_REQUEST_BYTES", "2")
    monkeypatch.setenv("PLANORA_MAX_IMPORT_REQUEST_BYTES", "32")

    default = _Handler(body=b'{"x":1}', headers={"Content-Length": "7"})
    assert http.parse_json(default) == {"x": 1}
    assert http.parse_json(_Handler()) == {}

    with pytest.raises(ValueError, match="2-byte"):
        http.parse_json(
            _Handler(
                path="/analytics/event",
                body=b"{} ",
                headers={"Content-Length": "3"},
            )
        )

    imported = _Handler(
        path="/import/csv?mode=test",
        body=b'{"rows":[]}',
        headers={"Content-Length": "11"},
    )
    assert http.parse_json(imported) == {"rows": []}

    with pytest.raises(ValueError, match="must be an object"):
        http.parse_json(_Handler(body=b"[]", headers={"Content-Length": "2"}))


def test_request_base_url_fail_closed_proxy_and_production_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http, "production_mode", lambda: False)
    monkeypatch.delenv("PLANORA_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PLANORA_DOMAIN", raising=False)
    monkeypatch.delenv("PLANORA_TRUST_PROXY_HEADERS", raising=False)
    assert http.request_base_url(_Handler(port=443)) == "https://127.0.0.1"
    assert http.request_base_url(_Handler(port=8123)) == "http://127.0.0.1:8123"

    monkeypatch.setenv("PLANORA_TRUST_PROXY_HEADERS", "true")
    trusted = _Handler(
        port=8123,
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "planora.example:8443",
        },
    )
    assert http.request_base_url(trusted) == "https://planora.example:8443"
    invalid = _Handler(
        port=8123,
        headers={"X-Forwarded-Proto": "ftp", "X-Forwarded-Host": "bad:99999"},
    )
    assert http.request_base_url(invalid) == "http://127.0.0.1:8123"

    monkeypatch.setenv("PLANORA_PUBLIC_BASE_URL", "https://public.example/")
    assert http.request_base_url(_Handler()) == "https://public.example"

    monkeypatch.delenv("PLANORA_PUBLIC_BASE_URL")
    monkeypatch.setattr(http, "production_mode", lambda: True)
    monkeypatch.setenv("PLANORA_DOMAIN", "planora.example")
    assert http.request_base_url(_Handler()) == "https://planora.example"
    monkeypatch.delenv("PLANORA_DOMAIN")
    with pytest.raises(RuntimeError, match="PLANORA_PUBLIC_BASE_URL"):
        http.request_base_url(_Handler())


def test_segments_decodes_nonempty_path_components() -> None:
    assert http.segments("/projects/A%20B/schedule?x=1") == [
        "projects",
        "A B",
        "schedule",
    ]
