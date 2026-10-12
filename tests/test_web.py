"""web.py tests: overview serialization + hub/standalone dual registration.

桩模式专用（与 conftest 一致，即使装了真 HA 也走桩）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import conftest  # noqa: I001 — pytest 路径由 conftest 铺

import custom_components.lux_balance.web as web

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeBus:
    def __init__(self):
        self.fired = []
        self.listen_once = []

    def async_fire(self, event_type, data=None):
        self.fired.append((event_type, data))

    def async_listen_once(self, event_type, cb):
        self.listen_once.append((event_type, cb))
        return lambda: None


class FakeHttp:
    def __init__(self):
        self.views = []
        self.static = []

    def register_view(self, view):
        self.views.append(view)

    async def async_register_static_paths(self, configs):
        self.static.extend(configs)


class FakeServices:
    def __init__(self):
        self.registered = {}

    def async_register(self, domain, service, handler, schema=None):
        self.registered[(domain, service)] = handler

    def has_service(self, domain, service):
        return (domain, service) in self.registered

    def async_remove(self, domain, service):
        self.registered.pop((domain, service), None)


class FakeHass:
    def __init__(self):
        self.data = {}
        self.bus = FakeBus()
        self.http = FakeHttp()
        self.services = FakeServices()


class FakeRequest:
    def __init__(self, hass):
        self.app = {"hass": hass}


def fake_runtime(entry_id="e1", zone="卫生间", **overrides):
    """A ZoneRuntime stand-in with only the attributes web.py reads."""
    curve = SimpleNamespace(
        points=[(0.0, 0.0), (50.25, 111.234), (100.0, 239.8)],
        source="calibrated",
        max_lux=239.8,
        slope_20_80=2.412,
    )
    rt = SimpleNamespace(
        entry_id=entry_id,
        zone_name=zone,
        mode="active",
        cal_progress="",
        target_lux=150.0,
        commanded_pct=45.0,
        lux_stale=False,
        curve=curve,
        decisions=["22:41:03 [lux] → set 45%"],
        last_decision=SimpleNamespace(ambient_lux=42.5, needed_lux=107.5),
        last_adjustment=datetime(2026, 10, 13, 12, 0, 0),
        light_entity="light.bath",
        lux_entity="sensor.bath_lux",
    )
    for k, v in overrides.items():
        if k == "curve" and v is None:
            rt.curve = None
        else:
            setattr(rt, k, v)
    return rt


def reset_registry(entries=None):
    stub = conftest._ENTITY_REGISTRY
    stub._entries_for = entries or {}
    return stub


def view_of(hass):
    return hass.http.views[0]


# ---------------------------------------------------------------------------
# Overview serialization
# ---------------------------------------------------------------------------


def test_overview_success():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {
        "e2": fake_runtime("e2", "更衣间", mode="idle", commanded_pct=None),
        "e1": fake_runtime("e1", "卫生间"),
    }
    reset_registry({"e1": []})
    resp = asyncio.run(web.OverviewView().get(FakeRequest(hass)))
    payload = json.loads(json.dumps(resp.payload, allow_nan=False))
    zones = payload["zones"]
    assert [z["zone_name"] for z in zones] == ["卫生间", "更衣间"]  # sorted
    z = zones[0]
    assert z["mode"] == "active"
    assert z["target_lux"] == 150.0
    assert z["commanded_pct"] == 45.0
    assert z["curve"]["source"] == "calibrated"
    assert z["curve"]["points"] == [[0.0, 0.0], [50.2, 111.23], [100.0, 239.8]]
    assert z["curve"]["max_lux"] == 239.8
    assert z["decisions"] == ["22:41:03 [lux] → set 45%"]
    assert z["ambient_lux_est"] == 42.5
    assert z["light_entity"] == "light.bath"
    assert z["calibrate_entity_ids"] == ["light.bath", "sensor.bath_lux"]
    z2 = zones[1]
    assert z2["commanded_pct"] is None
    assert z2["curve"]["points"] == [[0.0, 0.0], [50.2, 111.23], [100.0, 239.8]]


def test_overview_empty_zones():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {}
    resp = asyncio.run(web.OverviewView().get(FakeRequest(hass)))
    assert resp.payload == {"zones": []}


def test_overview_drops_nonfinite_curve_points():
    hass = FakeHass()
    rt = fake_runtime("e1", "卫生间")
    rt.curve.points = [(0.0, 0.0), (50.0, float("nan")), (100.0, 200.0)]
    hass.data[web.DOMAIN] = {"e1": rt}
    reset_registry()
    resp = asyncio.run(web.OverviewView().get(FakeRequest(hass)))
    pts = resp.payload["zones"][0]["curve"]["points"]
    assert pts == [[0.0, 0.0], [100.0, 200.0]]


def test_overview_no_curve_and_no_last_decision():
    hass = FakeHass()
    rt = fake_runtime(
        "e1", "卫生间", curve=None, last_decision=None, last_adjustment=None
    )
    hass.data[web.DOMAIN] = {"e1": rt}
    reset_registry()
    resp = asyncio.run(web.OverviewView().get(FakeRequest(hass)))
    z = resp.payload["zones"][0]
    assert z["curve"] is None
    assert z["ambient_lux_est"] is None
    assert z["needed_lux"] is None
    assert z["last_adjustment"] is None


def test_overview_number_entity_from_registry():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"e1": fake_runtime("e1")}
    entry = SimpleNamespace(entity_id="number.bath_target", platform="number")
    reset_registry({"e1": [entry]})
    resp = asyncio.run(web.OverviewView().get(FakeRequest(hass)))
    z = resp.payload["zones"][0]
    assert z["number_entity"] == "number.bath_target"
    # registry entities join the calibration targeting set
    assert "number.bath_target" in z["calibrate_entity_ids"]


def test_view_gates():
    hass = FakeHass()
    asyncio.run(web.async_setup_web(hass))
    view = view_of(hass)
    assert view.requires_auth is True
    assert getattr(view.get, "_require_admin_applied", False) is True


# ---------------------------------------------------------------------------
# Registration dual-path
# ---------------------------------------------------------------------------


def test_setup_web_idempotent():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {}
    asyncio.run(web.async_setup_web(hass))
    asyncio.run(web.async_setup_web(hass))
    assert len(hass.http.views) == 1
    assert len(hass.http.static) == 1
    assert hass.http.static[0].url_path == web.URL_BASE
    assert hass.http.static[0].cache_headers is False


def test_register_hub_mode():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"e1": fake_runtime()}
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    d = hass.data[web.REGISTRY_KEY].get(web.PAGE_ID)
    assert d is not None
    assert d["id"] == "luxbalance.main"
    assert d["element"] == "lux-balance-page"
    assert d["module_url"].startswith("/lux_balance/page.js?ver=")
    assert d["version"] == "0.3.0"
    # no standalone panel in hub mode
    assert web.STANDALONE_PANEL_URL_PATH not in hass.data.get("frontend_panels", {})
    assert (
        "fumiha_hub_page_changed",
        {"id": web.PAGE_ID, "action": "register"},
    ) in hass.bus.fired


def test_register_standalone_mode():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"e1": fake_runtime()}
    asyncio.run(web.async_setup_web(hass))
    panel = hass.data.get("frontend_panels", {}).get(web.STANDALONE_PANEL_URL_PATH)
    assert panel is not None
    cfg = panel["config"]["_panel_custom"]
    assert cfg["name"] == "lux-balance-page"
    assert cfg["module_url"].startswith("/lux_balance/page.js?ver=0.3.0")
    assert panel["require_admin"] is True
    # no descriptor without the hub
    assert web.REGISTRY_KEY not in hass.data


def test_unload_keeps_registration_while_zones_remain():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"e1": fake_runtime()}
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    web.async_unload_web(hass)  # zones remain → nothing torn down
    assert web.PAGE_ID in hass.data[web.REGISTRY_KEY]


def test_unload_hub_mode_pops_descriptor_and_fires():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {}
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    web.async_unload_web(hass)
    assert web.PAGE_ID not in hass.data[web.REGISTRY_KEY]
    assert (
        "fumiha_hub_page_changed",
        {"id": web.PAGE_ID, "action": "unregister"},
    ) in hass.bus.fired


def test_unload_standalone_mode_removes_panel():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {}
    asyncio.run(web.async_setup_web(hass))
    assert web.STANDALONE_PANEL_URL_PATH in hass.data["frontend_panels"]
    web.async_unload_web(hass)
    assert web.STANDALONE_PANEL_URL_PATH not in hass.data["frontend_panels"]


def test_started_recheck_switches_standalone_to_hub():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"e1": fake_runtime()}
    asyncio.run(web.async_setup_web(hass))
    flags = hass.data[web.WEB_DATA_KEY]
    assert flags["page_registered"] == "standalone"

    # Hub appears later (load-order race): one recheck is armed at started.
    assert hass.bus.listen_once, "started recheck must be armed"
    event_type, cb = hass.bus.listen_once[0]
    assert event_type == "homeassistant_started"

    hass.data[web.REGISTRY_KEY] = {}
    cb(None)  # simulate HA started
    assert web.PAGE_ID in hass.data[web.REGISTRY_KEY]
    assert flags["page_registered"] == "hub"
    assert web.STANDALONE_PANEL_URL_PATH not in hass.data["frontend_panels"]
    assert (
        "fumiha_hub_page_changed",
        {"id": web.PAGE_ID, "action": "register"},
    ) in hass.bus.fired


def test_started_recheck_noop_when_already_hub():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"e1": fake_runtime()}
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    _, cb = hass.bus.listen_once[0]
    fired_before = len(hass.bus.fired)
    before = hass.data[web.REGISTRY_KEY][web.PAGE_ID]
    cb(None)
    # 身份断言：descriptor 对象必须原样（重写会换新对象）；且不得多发 bus 事件
    assert hass.data[web.REGISTRY_KEY][web.PAGE_ID] is before
    assert len(hass.bus.fired) == fired_before


# ---------------------------------------------------------------------------
# LX-F-006 / 模式切换（修复回归）
# ---------------------------------------------------------------------------


def test_overview_curve_recomputes_cleaned_scalars():
    """LX-F-030: 点集 ≥2 存活而 max_lux/slope 非有限时，服务端从剩余点重算。"""
    hass = FakeHass()
    rt = fake_runtime("e1", "卫生间")
    rt.curve.points = [(0.0, 0.0), (20.0, 50.0), (80.0, 170.0)]
    rt.curve.max_lux = float("inf")
    rt.curve.slope_20_80 = float("nan")
    hass.data[web.DOMAIN] = {"e1": rt}
    reset_registry()
    resp = asyncio.run(web.OverviewView().get(FakeRequest(hass)))
    payload = json.loads(json.dumps(resp.payload, allow_nan=False))
    curve = payload["zones"][0]["curve"]
    assert curve is not None and len(curve["points"]) == 3
    assert curve["max_lux"] == 170.0  # 剩余点集最大值
    assert curve["slope_20_80"] == round((170.0 - 50.0) / 60.0, 2)  # p80-p20


def test_overview_inf_scalars_become_none_and_short_curve_is_none():
    hass = FakeHass()
    rt = fake_runtime("e1", "卫生间")
    rt.curve.max_lux = float("inf")
    rt.curve.slope_20_80 = float("nan")
    rt.curve.points = [(0.0, 0.0), (100.0, float("inf"))]  # 清洗后只剩 1 点
    rt.last_decision = SimpleNamespace(ambient_lux=float("inf"), needed_lux=5.0)
    rt.target_lux = float("nan")
    hass.data[web.DOMAIN] = {"e1": rt}
    reset_registry()
    resp = asyncio.run(web.OverviewView().get(FakeRequest(hass)))
    # allow_nan=False：任何 NaN/Infinity 残留都会让这一行炸
    payload = json.loads(json.dumps(resp.payload, allow_nan=False))
    z = payload["zones"][0]
    assert z["curve"] is None  # <2 点 → 视同未标定
    assert z["target_lux"] is None
    assert z["ambient_lux_est"] is None
    assert z["needed_lux"] == 5.0


def test_mode_switch_standalone_to_hub_on_reregister():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"e1": fake_runtime()}
    asyncio.run(web.async_setup_web(hass))
    assert hass.data[web.WEB_DATA_KEY]["page_registered"] == "standalone"
    # 壳随后出现（key 由壳 setup 创建）——重载本集成触发 setup_web 重判
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    flags = hass.data[web.WEB_DATA_KEY]
    assert flags["page_registered"] == "hub"
    assert web.PAGE_ID in hass.data[web.REGISTRY_KEY]
    assert web.STANDALONE_PANEL_URL_PATH not in hass.data.get("frontend_panels", {})
    actions = [
        d.get("action") for t, d in hass.bus.fired if t == "fumiha_hub_page_changed"
    ]
    # standalone 面板注销不发 bus 事件，只有 hub 方向的 register 会发
    assert actions == ["register"]


def test_mode_switch_hub_to_standalone_when_hub_removed():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"e1": fake_runtime()}
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    assert hass.data[web.WEB_DATA_KEY]["page_registered"] == "hub"
    # 壳条目被删除：hub 的 async_remove_entry 会清掉 registry dict
    del hass.data[web.REGISTRY_KEY]
    asyncio.run(web.async_setup_web(hass))
    flags = hass.data[web.WEB_DATA_KEY]
    assert flags["page_registered"] == "standalone"
    assert web.STANDALONE_PANEL_URL_PATH in hass.data.get("frontend_panels", {})


def test_manifest_declares_web_dependencies():
    import json as _json
    from pathlib import Path as _Path

    mf = _Path(__file__).resolve().parents[1] / "custom_components" / "lux_balance"
    mf = mf / "manifest.json"
    m = _json.loads(mf.read_text(encoding="utf-8"))
    assert m["dependencies"] == ["http", "frontend"]
    assert m["after_dependencies"] == ["fumiha_hub"]


# ---------------------------------------------------------------------------
# calibrate 服务三路语义（LX-F-021 / LX-F-025）
# ---------------------------------------------------------------------------


def _make_extract(extracted):
    async def _extract(hass, call):
        return set(extracted)

    return _extract


def _register_calibrate(hass):
    """注册校准服务，返回 handler 所在模块（供测试打桩）。"""
    import custom_components.lux_balance as pkg

    pkg._register_services(hass)
    return pkg


def _zone_runtimes(monkeypatch, behaviors):
    """按 {entry_id: start_calibration 返回值} 建 runtime 并打桩。"""
    runtimes = {}
    for eid, ok in behaviors.items():
        rt = fake_runtime(eid, f"区-{eid}")
        monkeypatch.setattr(rt, "start_calibration", lambda ok=ok: ok, raising=False)
        runtimes[eid] = rt
    return runtimes


def test_calibrate_no_target_starts_first_only(monkeypatch):
    import custom_components.lux_balance as pkg

    monkeypatch.setattr(
        pkg, "async_extract_entity_ids", _make_extract(set()), raising=False
    )
    hass = FakeHass()
    _register_calibrate(hass)
    handler = hass.services.registered[("lux_balance", "calibrate")]
    r1 = fake_runtime("e1", "区一")
    r2 = fake_runtime("e2", "区二")
    monkeypatch.setattr(r1, "start_calibration", lambda: True, raising=False)
    monkeypatch.setattr(r2, "start_calibration", lambda: False, raising=False)
    hass.data[web.DOMAIN] = {"e1": r1, "e2": r2}
    reset_registry()
    # 不带目标：第一区启动即成功，互斥跳过只记日志——不抛（0.2.0 契约，LX-F-021）
    asyncio.run(handler(SimpleNamespace(data={})))
    # start_calibration 顺序不确定，但整体不抛即语义成立


def test_calibrate_targeted_skip_raises(monkeypatch):
    import custom_components.lux_balance as pkg

    monkeypatch.setattr(
        pkg, "async_extract_entity_ids", _make_extract({"light.bath"}), raising=False
    )
    hass = FakeHass()
    _register_calibrate(hass)
    handler = hass.services.registered[("lux_balance", "calibrate")]
    # fake_runtime 默认 light_entity="light.bath"：目标两区都命中，
    # 区二因互斥 skip——这正是断言 called 含 r1 的前提。
    r1 = fake_runtime("e1", "区一")
    r2 = fake_runtime("e2", "区二")
    hass.data[web.DOMAIN] = {"e1": r1, "e2": r2}
    reset_registry()
    called = []
    monkeypatch.setattr(
        r1, "start_calibration", lambda: called.append("r1") or True, raising=False
    )
    monkeypatch.setattr(
        r2, "start_calibration", lambda: called.append("r2") or False, raising=False
    )
    try:
        asyncio.run(handler(SimpleNamespace(data={"entity_id": ["light.bath"]})))
        raised = None
    except Exception as err:  # HomeAssistantError 桩
        raised = err
    assert "r1" in called and "r2" in called  # 命中区都尝试过
    assert raised is not None and "区二" in str(raised)


def test_calibrate_target_miss_raises(monkeypatch):
    import custom_components.lux_balance as pkg

    monkeypatch.setattr(
        pkg, "async_extract_entity_ids", _make_extract({"light.nowhere"}), raising=False
    )
    hass = FakeHass()
    _register_calibrate(hass)
    handler = hass.services.registered[("lux_balance", "calibrate")]
    rt = fake_runtime("e1", "区一")
    monkeypatch.setattr(rt, "start_calibration", lambda: True, raising=False)
    hass.data[web.DOMAIN] = {"e1": rt}
    reset_registry()
    try:
        asyncio.run(handler(SimpleNamespace(data={"entity_id": ["light.nowhere"]})))
        raised = None
    except Exception as err:
        raised = err
    assert raised is not None and "未命中" in str(raised)


def test_calibrate_target_resolves_to_nothing_raises(monkeypatch):
    """LX-F-032: 点名但 extract 解析为空 → 必须响，不得回落全局扫描。"""
    import custom_components.lux_balance as pkg

    monkeypatch.setattr(
        pkg, "async_extract_entity_ids", _make_extract(set()), raising=False
    )
    hass = FakeHass()
    _register_calibrate(hass)
    handler = hass.services.registered[("lux_balance", "calibrate")]
    rt = fake_runtime("e1", "区一")
    monkeypatch.setattr(rt, "start_calibration", lambda: True, raising=False)
    hass.data[web.DOMAIN] = {"e1": rt}
    reset_registry()
    try:
        asyncio.run(handler(SimpleNamespace(data={"entity_id": ["light.gone"]})))
        raised = None
    except Exception as err:
        raised = err
    assert raised is not None and "未解析" in str(raised)


def test_calibrate_targeted_all_start(monkeypatch):
    import custom_components.lux_balance as pkg

    monkeypatch.setattr(
        pkg, "async_extract_entity_ids", _make_extract({"light.bath"}), raising=False
    )
    hass = FakeHass()
    _register_calibrate(hass)
    handler = hass.services.registered[("lux_balance", "calibrate")]
    rt = fake_runtime("e1", "区一")
    monkeypatch.setattr(rt, "start_calibration", lambda: True, raising=False)
    hass.data[web.DOMAIN] = {"e1": rt}
    reset_registry()
    asyncio.run(handler(SimpleNamespace(data={"entity_id": ["light.bath"]})))  # 不抛
