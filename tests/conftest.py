"""Pytest configuration for the lux_balance integration tests.

Adds the integration package to sys.path and installs stub Home Assistant
modules so the shell (config_flow) tests can run standalone.

这套壳层测试是「桩模式专用」：即使环境里装了真实 HA 也使用桩
（真实 HA 下 flow.config_entry 为只读属性，测试无法运行）。
"""

import sys as _sys
import types as _types
from datetime import datetime as _datetime
from pathlib import Path
from typing import Any as _Any  # noqa: E402 — 路径垫片必须在导入前就位

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "lux_balance"
_sys.path.insert(0, str(PACKAGE))


def _ha_module(name: str, **attrs: _Any) -> _types.ModuleType:
    mod = _types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    _sys.modules[name] = mod
    return mod


def _identity(x):
    return x


class _ConfigEntry:
    pass


class _ConfigFlowBase:
    """Base providing the flow helpers config_flow.py calls."""

    def __init_subclass__(cls, **kwargs):
        # 吞掉 HA 的 domain= 等类关键字，不转发给 object
        super().__init_subclass__()

    def __init__(self) -> None:
        self.context: dict = {}
        self.unique_id = None
        self._reconfigure_entry = None

    def add_suggested_values_to_schema(self, schema, suggested_values):
        return schema

    async def async_set_unique_id(self, unique_id, raise_on_progress=True):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self, error=None):
        # tests monkeypatch this to simulate conflicts
        return None

    # HA 真源码里这三个是 @callback 同步方法（集成代码不带 await 直接 return）
    def async_show_form(
        self, step_id, data_schema=None, errors=None, description_placeholders=None
    ):
        # 桩保留 data_schema，供测试断言表单字段集合
        return {
            "type": "form",
            "step_id": step_id,
            "errors": errors,
            "data_schema": data_schema,
        }

    def async_create_entry(self, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_update_reload_and_abort(
        self, entry, data=None, unique_id=None, title=None
    ):
        if isinstance(entry, dict):
            entry["data"] = data
            entry["unique_id"] = unique_id
            entry["title"] = title
        else:
            if data is not None:
                entry.data = data
            if unique_id is not None:
                entry.unique_id = unique_id
            if title is not None:
                entry.title = title
        return {"type": "abort", "reason": "reconfigure_successful"}

    def _get_reconfigure_entry(self):
        return self._reconfigure_entry


class _Store:
    def __init__(self, hass, version, key, **kwargs):
        self.hass = hass
        self.version = version
        self.key = key

    async def async_load(self):
        return None

    async def async_save(self, data):
        return None

    async def async_remove(self):
        return None


class _Selector:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return None  # 可调用：让 voluptuous 把桩实例当作普通 validator 编译


class _SelectorMode:
    BOX = "box"
    SLIDER = "slider"
    DROPDOWN = "dropdown"
    LIST = "list"


class _HomeAssistantError(Exception):
    pass


_ha_module("homeassistant")
_sys.modules["homeassistant"].__path__ = []  # 使其成为包，允许注册子模块
_ha_module("homeassistant.components")
_ha_module(
    "homeassistant.components.light",
    ATTR_BRIGHTNESS="brightness",
    ATTR_BRIGHTNESS_PCT="brightness_pct",
    ColorMode=_types.SimpleNamespace(BRIGHTNESS="brightness"),
    LightEntity=type("LightEntity", (), {}),
)
_ha_module(
    "homeassistant.config_entries",
    ConfigEntry=_ConfigEntry,
    ConfigFlow=type("ConfigFlow", (_ConfigFlowBase,), {}),
    ConfigFlowResult=dict,
    OptionsFlow=type("OptionsFlow", (_ConfigFlowBase,), {}),
)
_ha_module(
    "homeassistant.const",
    STATE_ON="on",
    STATE_OFF="off",
    STATE_UNAVAILABLE="unavailable",
    STATE_UNKNOWN="unknown",
    ATTR_ENTITY_ID="entity_id",
)
_ha_module(
    "homeassistant.core",
    Event=type("Event", (), {}),
    EventStateChangedData=type("EventStateChangedData", (), {}),
    HomeAssistant=type("HomeAssistant", (), {}),
    ServiceCall=type("ServiceCall", (), {}),
    callback=_identity,
)
_ha_module("homeassistant.exceptions", HomeAssistantError=_HomeAssistantError)
_ha_module("homeassistant.helpers")
_ha_module(
    "homeassistant.helpers.dispatcher",
    async_dispatcher_connect=lambda *a, **k: lambda: None,
    async_dispatcher_send=lambda *a, **k: None,
    dispatcher_send=lambda *a, **k: None,
)
_ha_module(
    "homeassistant.helpers.event",
    async_call_later=lambda *a, **k: lambda: None,
    async_track_state_change_event=lambda *a, **k: lambda: None,
    async_track_time_interval=lambda *a, **k: lambda: None,
)
_ha_module(
    "homeassistant.helpers.service",
    async_extract_entity_ids=lambda *a, **k: [],
)
_ha_module(
    "homeassistant.helpers.config_validation",
    config_entry_only_config_schema=lambda domain: None,
)
_ha_module("homeassistant.helpers.storage", Store=_Store)
_ha_module(
    "homeassistant.helpers.entity_registry",
    async_get=lambda hass: _types.SimpleNamespace(async_get=lambda eid: None),
)
_ha_module("homeassistant.helpers.device_registry", DeviceInfo=dict)
_ha_module(
    "homeassistant.helpers.selector",
    TextSelector=_Selector,
    TextSelectorConfig=_Selector,
    TextSelectorType=_types.SimpleNamespace(TEXT="text"),
    EntitySelector=_Selector,
    EntitySelectorConfig=_Selector,
    NumberSelector=_Selector,
    NumberSelectorConfig=_Selector,
    NumberSelectorMode=_SelectorMode,
    BooleanSelector=_Selector,
    SelectSelector=_Selector,
    SelectSelectorConfig=_Selector,
    SelectSelectorMode=_SelectorMode,
)

# homeassistant.util.dt：runtime 只用 now()/utcnow()/as_utc()
_dt_mod = _types.ModuleType("homeassistant.util.dt")
_dt_mod.now = lambda *a, **k: _datetime.now()
_dt_mod.utcnow = lambda: _datetime.now()
_dt_mod.as_utc = lambda x: x
_ha_module("homeassistant.util", dt=_dt_mod)

# 子模块挂到父模块属性上，供 from homeassistant.helpers import X 使用
for name in [m for m in list(_sys.modules) if m.startswith("homeassistant.")]:
    parent_name, _, child = name.rpartition(".")
    parent = _sys.modules.get(parent_name)
    if parent is not None:
        setattr(parent, child, _sys.modules[name])
