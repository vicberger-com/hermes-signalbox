"""1.1 install-as-a-service fixes: Signalbox hosted by Hermes, reached from the CLI (EVAL-1.1 S-1 to S-8).

Under Hermes the hosting process serves the loopback API with the restricted ``dashboard`` profile (M9).
The CLI must still work: offline commands run on the data directory, read-only ``module health`` is served,
and a refused command names the routes that work.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
import types
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from sy_testing import write_module

from hermes_signalbox.api import ApiClient, ApiRestricted, ControlServer
from hermes_signalbox.cli import main
from hermes_signalbox.core import Core

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALBOX_DATA_DIR", raising=False)


@pytest.fixture
def hosted(tmp_path: Path) -> Iterator[tuple[Core, Path]]:
    """A data directory hosted the way the Hermes adapter hosts it: Core plus the dashboard-profile API."""
    data = tmp_path / "data"
    write_module(data / "modules", "ext", isolation="subprocess", request=("schedule",))
    core = Core(data_dir=data, hosting=True)
    server = ControlServer(core, profile="dashboard")
    server.start()
    try:
        yield core, data
    finally:
        server.shutdown()
        core.close()


def test_s4_offline_commands_work_while_hermes_hosts(
    hosted: tuple[Core, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    core, data = hosted
    assert main(["--data-dir", str(data), "module", "grant", "ext", "--capability", "schedule"]) == 0
    assert "schedule" in core.run("module", "show", {"id": "ext"}, actor="t")["granted"]
    assert main(["--data-dir", str(data), "module", "mode", "ext", "--mode", "manual"]) == 0
    assert main(["--data-dir", str(data), "config", "show"]) == 0
    out = capsys.readouterr()
    assert "data_dir" in out.out and "denied" not in out.err


def test_s4_health_is_served_by_the_hermes_api(
    hosted: tuple[Core, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    core, data = hosted
    core.run("module", "grant", {"id": "ext", "capability": "schedule"}, actor="t")
    core.run("module", "activate", {"id": "ext"}, actor="t")
    assert main(["--data-dir", str(data), "module", "health", "ext"]) == 0
    assert "ext is healthy" in capsys.readouterr().out  # H5 WP2 (#205): a sentence, not "ok: True"


def test_s4_refused_command_names_the_routes_that_work(
    hosted: tuple[Core, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, data = hosted
    with pytest.raises(ApiRestricted):
        ApiClient.from_data_dir(data).request("module", "check_updates", {})
    assert main(["--data-dir", str(data), "module", "check_updates"]) == 3
    err = capsys.readouterr().err
    assert "/signalbox module check_updates" in err and "hermes-signalbox api serve" in err
    assert "use the CLI" not in err


def test_s1_plugin_installs_nothing_into_the_hermes_environment() -> None:
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert manifest["python_runtime"] == "external"
    assert (
        tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"] == []
    )


def test_s3_shim_loads_its_own_source_before_any_installed_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / "decoy" / "hermes_signalbox"
    decoy.mkdir(parents=True)
    (decoy / "__init__.py").write_text("__version__ = 'decoy'\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "decoy"))
    for name in [m for m in sys.modules if m == "hermes_signalbox" or m.startswith("hermes_signalbox.")]:
        monkeypatch.delitem(sys.modules, name)
    spec = importlib.util.spec_from_file_location("signalbox_plugin_shim", ROOT / "__init__.py")
    assert spec is not None and spec.loader is not None
    shim = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "signalbox_plugin_shim", shim)
    spec.loader.exec_module(shim)
    loaded = sys.modules["hermes_signalbox"]
    assert isinstance(loaded, types.ModuleType)
    assert Path(loaded.__file__ or "").resolve().parent == (ROOT / "src" / "hermes_signalbox").resolve()
