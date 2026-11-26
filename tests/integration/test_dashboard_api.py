"""The dashboard backend (``dashboard/plugin_api.py``) under real FastAPI (H1 D-22, C-18 #116 #117).

Runs in the ``hermes-integration`` CI job, whose environment is Hermes's own (FastAPI, Starlette and httpx
come from Hermes's lock); skipped where FastAPI is not installed.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest

if os.environ.get("SIGNALBOX_REQUIRE_HERMES") == "1":  # the CI job that installs Hermes: never skip there
    import fastapi
    from fastapi.testclient import TestClient
else:
    fastapi = pytest.importorskip("fastapi", reason="FastAPI is not installed")
    pytest.importorskip("httpx", reason="httpx is not installed")
    from fastapi.testclient import TestClient

PLUGIN_API = Path(__file__).resolve().parents[2] / "dashboard" / "plugin_api.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("signalbox_dashboard_api_under_test", PLUGIN_API)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SIGNALBOX_DATA_DIR", str(tmp_path / "data"))  # no daemon there: the API is "off"
    app = fastapi.FastAPI()
    app.include_router(_load().router, prefix="/api/plugins/signalbox")
    return TestClient(app)


def test_d22_a_read_route_reports_the_api_off_as_503(client: TestClient) -> None:
    r = client.get("/api/plugins/signalbox/modules")
    assert r.status_code == 503 and "enabled = true" in r.json()["detail"]


@pytest.mark.parametrize(
    "path",
    ["/modules/Bad-Name", "/panel/router/..%2Fx", "/modules/a"],
)
def test_d22_path_parameters_are_validated(client: TestClient, path: str) -> None:
    assert client.get("/api/plugins/signalbox" + path).status_code in (400, 404)


def test_d22_only_activate_and_deactivate_are_lifecycle_verbs(client: TestClient) -> None:
    assert client.post("/api/plugins/signalbox/modules/router/remove").status_code == 404
    assert client.get("/api/plugins/signalbox/report/secrets").status_code == 404
    assert client.get("/api/plugins/signalbox/inbox?state=bogus").status_code == 400
    assert client.post("/api/plugins/signalbox/inbox/not-hex/ack").status_code == 400


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
@pytest.mark.parametrize(
    "path", ["/modules/router/deactivate", "/inbox/0123456789abcdef/ack", "/inbox/ack_all"]
)
def test_c18_a_write_another_page_sent_is_refused(client: TestClient, site: str, path: str) -> None:
    r = client.post("/api/plugins/signalbox" + path, headers={"Sec-Fetch-Site": site})
    assert r.status_code == 403


@pytest.mark.parametrize("headers", [{"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {}])
def test_c18_the_dashboards_own_writes_still_reach_signalbox(
    client: TestClient, headers: dict[str, str]
) -> None:
    # Past the page check the request reaches the (absent) daemon: 503, not 403.
    r = client.post("/api/plugins/signalbox/modules/router/deactivate", headers=headers)
    assert r.status_code == 503


def test_s3_3_every_sec_fetch_site_value_is_checked(client: TestClient) -> None:
    # Two values, one of them cross-site: Hermes's own gate checks all of them, so does the plugin.
    r = client.post(
        "/api/plugins/signalbox/modules/router/deactivate",
        headers=[("Sec-Fetch-Site", "none"), ("Sec-Fetch-Site", "cross-site")],
    )
    assert r.status_code == 403


def test_h5_wp3_mode_route_with_the_real_fastapi(client: TestClient) -> None:
    """The mode route is matched before the generic lifecycle route, validates its body, is refused for
    another page, and serves the static labels with the API off."""
    base = "/api/plugins/signalbox"
    assert client.post(base + "/modules/router/mode", json={"mode": "always"}).status_code == 400
    assert client.post(base + "/modules/router/mode", content=b"not json").status_code == 400
    assert client.post(base + "/modules/Bad..Id/mode", json={"mode": "auto"}).status_code in (400, 404)
    crossed = client.post(
        base + "/modules/router/mode", json={"mode": "auto"}, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert crossed.status_code == 403
    assert client.post(base + "/modules/router/mode", json={"mode": "auto"}).status_code == 503  # API off
    labels = client.get(base + "/labels")
    assert labels.status_code == 200 and "hermes.hooks" in labels.json()["capabilities"]
