"""M2 resource registry: reviewed imports, pools, bindings, resolve, model read-only rule."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from switchyard.contract import run_contract
from switchyard.core import BUILTIN_MODULES, Core
from switchyard.errors import SwitchyardError

pytestmark = pytest.mark.bundled_modules
MODULE_DIR = Path(BUILTIN_MODULES) / "resources"

MODELS_DEV = {
    "openrouter": {
        "id": "openrouter",
        "api": "https://example.invalid",
        "env": ["OPENROUTER_API_KEY"],
        "models": {
            "meta/llama-4:free": {
                "name": "Llama 4 (free)",
                "cost": {"input": 0, "output": 0},
                "tool_call": True,
                "limit": {"context": 131072, "output": 8192},
            },
            "big/paid": {
                "name": "Big",
                "cost": {"input": 3, "output": 15},
                "reasoning": True,
                "modalities": {"input": ["text", "image"]},
            },
            "bad id with spaces": {"name": "x"},
        },
    },
    "ollama": {"models": {"qwen3": {"name": "Qwen3", "open_weights": True}}},
    "skipped": "not an object",
}


def act(core: Core, action: str, actor: str = "t", **args: Any) -> Any:
    return core.run("module", "action", {"id": "resources", "action": action, "args": args}, actor=actor)


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHYARD_DATA_DIR", raising=False)


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Core]:
    cache = tmp_path / "models_dev_cache.json"
    cache.write_text(json.dumps(MODELS_DEV), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.toml").write_text(f"[modules.resources]\nmodels_dev_cache = {json.dumps(str(cache))}\n",
                                      encoding="utf-8")  # fmt: skip
    c = Core(data_dir=data, hosting=True)
    for cap in ("fs.read", "ui.panel"):
        c.run("module", "grant", {"id": "resources", "capability": cap}, actor="t")
    c.run("module", "activate", {"id": "resources"}, actor="t")
    yield c
    c.close()


def test_contract_suite() -> None:
    report = run_contract(MODULE_DIR)
    assert report.ok, report.summary()


def test_import_is_reviewed_and_never_enables(core: Core) -> None:
    with pytest.raises(SwitchyardError, match="read-only"):  # R1: a preview replaces the pending one
        act(core, "import_preview", actor="hermes")
    preview = act(core, "import_preview")
    assert preview["cost_changes"] == []
    assert (preview["added"], preview["changed"], preview["removed"]) == (3, 0, 0)
    assert act(core, "list")["count"] == 0  # nothing applied yet
    with pytest.raises(SwitchyardError, match="read-only"):
        act(core, "import_apply", actor="hermes", import_id=preview["import_id"])
    applied = act(core, "import_apply", import_id=preview["import_id"])
    assert applied["added"] == 3
    rows = {r["id"]: r for r in act(core, "list")["resources"]}
    assert {r["state"] for r in rows.values()} == {"disabled"}
    free = rows["openrouter/meta/llama-4:free"]
    assert free["cost_class"] == "free" and free["tags"] == ["tools"] and free["limits"]["context"] == 131072
    assert rows["openrouter/big/paid"]["cost_class"] == "paid" and rows["openrouter/big/paid"]["tags"] == [
        "reasoning",
        "vision",
    ]
    assert rows["ollama/qwen3"]["cost_class"] == "self-hosted"
    assert "OPENROUTER_API_KEY" not in json.dumps(rows) and "example.invalid" not in json.dumps(rows)
    with pytest.raises(SwitchyardError, match="no pending import"):
        act(core, "import_apply", import_id=preview["import_id"])


def test_reimport_diff_keeps_user_choices(core: Core, tmp_path: Path) -> None:
    act(core, "import_apply", import_id=act(core, "import_preview")["import_id"])
    act(core, "set_state", id="openrouter/big/paid", state="manual")
    act(core, "set_priority", id="openrouter/big/paid", priority=5)
    act(core, "tag", id="openrouter/big/paid", tag="mine")
    changed = json.loads(json.dumps(MODELS_DEV))
    changed["openrouter"]["models"]["big/paid"]["name"] = "Big v2"
    del changed["ollama"]
    cache = tmp_path / "models_dev_cache.json"
    cache.write_text(json.dumps(changed), encoding="utf-8")
    preview = act(core, "import_preview")
    assert (preview["added"], preview["changed"], preview["removed"]) == (0, 1, 1)
    act(core, "import_apply", import_id=preview["import_id"])
    big = act(core, "show", id="openrouter/big/paid")
    assert (
        big["name"] == "Big v2"
        and big["state"] == "manual"
        and big["priority"] == 5
        and "mine" in big["tags"]
    )
    qwen = act(core, "show", id="ollama/qwen3")
    assert "stale" in qwen["tags"] and qwen["user_tags"] == []
    cache.write_text(json.dumps(MODELS_DEV), encoding="utf-8")  # listed again: stale clears
    act(core, "import_apply", import_id=act(core, "import_preview")["import_id"])
    assert "stale" not in act(core, "show", id="ollama/qwen3")["tags"]
    assert "mine" in act(core, "show", id="openrouter/big/paid")["tags"]


def test_filters_pools_bindings_and_resolve(core: Core) -> None:
    act(core, "import_apply", import_id=act(core, "import_preview")["import_id"])
    assert [r["id"] for r in act(core, "list", cost_class="free")["resources"]] == [
        "openrouter/meta/llama-4:free"
    ]
    assert act(core, "list", tag="vision")["count"] == 1
    assert act(core, "list", query="qwen")["count"] == 1 and act(core, "list", query="%")["count"] == 0
    assert act(core, "list", provider="ollama")["count"] == 1
    act(core, "pool_create", name="cheap", description="free first")
    act(core, "pool_add", pool="cheap", id="openrouter/meta/llama-4:free", priority=1)
    act(core, "pool_add", pool="cheap", id="ollama/qwen3", priority=2)
    act(core, "pool_add", pool="cheap", id="openrouter/big/paid", priority=3)
    act(core, "bind", consumer="main", pool="cheap")
    assert act(core, "resolve", actor="hermes", consumer="main")["resources"] == []  # all disabled
    for rid in ("ollama/qwen3", "openrouter/meta/llama-4:free"):
        act(core, "set_state", id=rid, state="auto")
    order = [r["id"] for r in act(core, "resolve", consumer="main")["resources"]]
    assert order == ["openrouter/meta/llama-4:free", "ollama/qwen3"]
    assert act(core, "list", pool="cheap")["count"] == 3
    assert act(core, "pools")["pools"][0] == {
        "name": "cheap",
        "description": "free first",
        "members": 3,
        "consumers": ["main"],
    }
    assert act(core, "show", id="ollama/qwen3")["pools"] == [{"pool": "cheap", "priority": 2}]
    with pytest.raises(SwitchyardError, match="bound"):
        act(core, "pool_delete", name="cheap")
    act(core, "unbind", consumer="main")
    assert act(core, "resolve", consumer="main")["pool"] is None
    act(core, "pool_remove", pool="cheap", id="ollama/qwen3")
    act(core, "untag", id="ollama/qwen3", tag="open-weights")
    assert act(core, "pool_delete", name="cheap")["deleted"] is True
    summary = core.run("module", "panel", {"id": "resources", "panel": "resources.status"}, actor="t")
    assert summary["resources"] == 3 and summary["enabled"] == 2 and summary["pools"] == 0
    assert "module.resources.bound" in [r["action"] for r in core.run("audit", "tail", {"n": 200}, actor="t")]


@pytest.mark.parametrize(
    ("action", "args"),
    [
        ("set_state", {"id": "x", "state": "on"}), ("set_state", {"id": "nope", "state": "auto"}),
        ("set_priority", {"id": "nope", "priority": 1}), ("set_priority", {"id": "x", "priority": 10**9}),
        ("pool_create", {"name": "Bad Name"}), ("bind", {"consumer": "anyone", "pool": "p"}),
        ("bind", {"consumer": "main", "pool": "missing"}), ("tag", {"id": "nope", "tag": "x"}),
        ("resolve", {"consumer": "x y"}), ("import_apply", {"import_id": "zz"}),
        ("import_discard", {"import_id": "abcdefabcdef"}), ("import_preview", {"path": "/etc/passwd"}),
        ("import_file", {"path": "relative.json"}), ("list", {"limit": 0}), ("list", {"tag": "BAD TAG"}),
        ("pool_add", {"pool": "missing", "id": "x"}),
    ],
)  # fmt: skip
def test_input_validation(core: Core, action: str, args: dict[str, Any]) -> None:
    with pytest.raises(SwitchyardError):
        act(core, action, **args)


def test_file_import_and_hostile_files(core: Core, tmp_path: Path) -> None:
    good = tmp_path / "catalog.json"
    entry = {"id": "local/agent", "kind": "agent", "cost_class": "self-hosted", "tags": ["ok", "BAD"],
             "limits": {"context": -1}}  # fmt: skip
    good.write_text(json.dumps({"resources": [entry]}), encoding="utf-8")
    preview = act(core, "import_file", path=str(good))
    act(core, "import_apply", import_id=preview["import_id"])
    row = act(core, "show", id="local/agent")
    assert (
        row["kind"] == "agent"
        and row["tags"] == ["ok"]
        and row["limits"] == {}
        and row["source"].startswith("file:")
        and row["source"].endswith(":catalog.json")
    )
    hostile = (
        {"resources": "x"},
        {"resources": [{"id": "../../x y"}]},
        {"resources": [{"id": "a", "kind": "rocket"}]},
        {"resources": [5]},
        [1, 2],
    )  # fmt: skip
    for i, bad in enumerate(hostile):
        path = tmp_path / f"bad{i}.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(SwitchyardError):
            act(core, "import_file", path=str(path))
    discard = act(core, "import_file", path=str(good))
    assert act(core, "import_discard", import_id=discard["import_id"])["discarded"] is True
    first = act(core, "import_file", path=str(good))["import_id"]
    second = act(core, "import_file", path=str(good))["import_id"]  # same source replaces the pending preview
    with pytest.raises(SwitchyardError, match="no pending import"):
        act(core, "import_apply", import_id=first)
    assert second != first
    for i in range(4):
        other = tmp_path / f"cat{i}.json"
        other.write_text(good.read_text(encoding="utf-8"), encoding="utf-8")
        act(core, "import_file", path=str(other))
    extra = tmp_path / "cat9.json"
    extra.write_text(good.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(SwitchyardError, match="pending"):
        act(core, "import_file", path=str(extra))
    assert (
        len(
            core.run("module", "panel", {"id": "resources", "panel": "resources.status"}, actor="t")[
                "pending_imports"
            ]
        )
        == 5
    )


def test_models_dev_parser_limits(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("m2catalog", MODULE_DIR / "catalog.py")
    assert spec is not None and spec.loader is not None
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    with pytest.raises(SwitchyardError):
        catalog.from_models_dev([], providers=set(), free_only=False)
    rows = catalog.from_models_dev(MODELS_DEV, providers={"openrouter"}, free_only=True)
    assert [r["id"] for r in rows] == ["openrouter/meta/llama-4:free"]
    huge = {"p": {"models": {f"m{i}": {} for i in range(catalog.MAX_ROWS + 2)}}}
    with pytest.raises(SwitchyardError, match="filter"):
        catalog.from_models_dev(huge, providers=set(), free_only=False)
    with pytest.raises(SwitchyardError):
        catalog.from_file({"resources": [{}] * (catalog.MAX_ROWS + 1)})


def test_bad_settings(tmp_path: Path) -> None:
    for i, setting in enumerate(('models_dev_cache = "relative.json"', "max_catalog_mb = 99", "other = 1")):
        data = tmp_path / f"d{i}"
        data.mkdir()
        (data / "config.toml").write_text(f"[modules.resources]\n{setting}\n", encoding="utf-8")
        with Core(data_dir=data, hosting=True) as c:
            for cap in ("fs.read", "ui.panel"):
                c.run("module", "grant", {"id": "resources", "capability": cap}, actor="t")
            c.run("module", "activate", {"id": "resources"}, actor="t")
            assert c.run("module", "show", {"id": "resources"}, actor="t")["status"] == "failed"


def test_model_cannot_choose_files(core: Core, tmp_path: Path) -> None:
    secret = tmp_path / "private.json"
    secret.write_text(json.dumps({"resources": [{"id": "x/y", "name": "private-name"}]}), encoding="utf-8")
    with pytest.raises(SwitchyardError, match="read-only"):
        act(core, "import_file", actor="hermes", path=str(secret))
    preview = act(core, "import_preview")
    assert set(preview["sample_ids"]) == {"added", "changed", "removed"}
    assert all(isinstance(i, str) for i in preview["sample_ids"]["added"])


def test_tag_filter_treats_underscore_literally_and_tag_cap(core: Core, tmp_path: Path) -> None:
    act(core, "import_apply", import_id=act(core, "import_preview")["import_id"])
    act(core, "tag", id="ollama/qwen3", tag="axb")
    assert act(core, "list", tag="a_b")["count"] == 0
    act(core, "tag", id="ollama/qwen3", tag="a_b")
    assert act(core, "list", tag="a_b")["count"] == 1
    many = tmp_path / "many.json"
    many.write_text(
        json.dumps({"resources": [{"id": "t/x", "tags": [f"t{i}" for i in range(40)]}]}), encoding="utf-8"
    )
    with pytest.raises(SwitchyardError, match="tags"):
        act(core, "import_file", path=str(many))


def test_cost_class_change_is_shown_and_demotes_to_manual(core: Core, tmp_path: Path) -> None:
    """R1 review: a paid resource relabelled free must not be routed free-first without a human."""
    act(core, "import_apply", import_id=act(core, "import_preview")["import_id"])
    act(core, "set_state", id="openrouter/big/paid", state="auto")
    relabelled = json.loads(json.dumps(MODELS_DEV))
    relabelled["openrouter"]["models"]["big/paid"]["cost"] = {"input": 0, "output": 0}
    (tmp_path / "models_dev_cache.json").write_text(json.dumps(relabelled), encoding="utf-8")
    preview = act(core, "import_preview")
    assert preview["cost_changes"] == [{"id": "openrouter/big/paid", "from": "paid", "to": "free"}]
    act(core, "import_apply", import_id=preview["import_id"])
    big = act(core, "show", id="openrouter/big/paid")
    assert big["cost_class"] == "free" and big["state"] == "manual"
