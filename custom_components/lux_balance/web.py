"""Web layer: overview REST view, static assets and the page registration.

The page (``static/page.js`` → ``<lux-balance-page>``) is served from this
integration and rendered either inside the Fumiha Hub shell (when the hub
integration is loaded) or as a standalone sidebar panel (when it is not).
Same view/panel architecture as the Stockroom / WHA-State-Scanner panels —
byte-proven against HA 2026.1.3 in production.

Hub coupling is contract-only (see the FumihaHub README): the contract is
the ``hass.data["fumiha_hub_registry"]`` dict plus the
``fumiha_hub_page_changed`` bus event. This module never imports
``fumiha_hub``.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from aiohttp import web

from homeassistant.components import frontend
from homeassistant.components.http import (
    HomeAssistantView,
    StaticPathConfig,
    require_admin,
)
from homeassistant.core import (
    EVENT_HOMEASSISTANT_STARTED,
    Event,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import dt as dt_util

from .const import DOMAIN, TARGET_MAX_LUX, TARGET_MIN_LUX, TARGET_STEP_LUX
from .runtime import ZoneRuntime

_LOGGER = logging.getLogger(__name__)

WEB_DATA_KEY = f"{DOMAIN}_web_registered"

URL_BASE = "/lux_balance"
API_BASE = "/api/lux_balance"

PAGE_ID = "luxbalance.main"
PAGE_TITLE = "亮度均衡"
PAGE_ICON = "mdi:tune-vertical"
PAGE_ELEMENT = "lux-balance-page"
STANDALONE_PANEL_URL_PATH = "lux-balance"

REGISTRY_KEY = "fumiha_hub_registry"
BUS_EVENT_PAGE_CHANGED = "fumiha_hub_page_changed"

# Keep vendored assets in lockstep with FumihaHub's static/ copies.


def _manifest_version(hass: HomeAssistant) -> str:
    """Manifest version as the asset cache buster ("dev" when unresolved)."""
    try:
        return async_get_loaded_integration(hass, DOMAIN).version or "dev"
    except Exception:  # noqa: BLE001 — version is only a cache buster
        _LOGGER.debug("Could not resolve integration version for page URL")
        return "dev"


def _descriptor(hass: HomeAssistant) -> dict:
    """The registry descriptor for this integration's page."""
    return {
        "id": PAGE_ID,
        "title": PAGE_TITLE,
        "icon": PAGE_ICON,
        "order": 10,
        "version": _manifest_version(hass),
        "module_url": f"{URL_BASE}/page.js?ver={_manifest_version(hass)}",
        "element": PAGE_ELEMENT,
    }


def _zone_entities(hass: HomeAssistant, runtime: ZoneRuntime) -> set[str]:
    """Every entity id that belongs to this zone, plus its raw config picks.

    Thin re-export of the calibration service's targeting helper
    (``__init__._zone_entities``): the service is the final authority on
    what a calibrate target hits, so the page must offer exactly the same
    set — a local copy would drift and resurface as "clicked calibrate,
    nothing happened" (LX-F-013). Deferred import: ``__init__`` imports
    this module at setup, so a module-level import would be circular.
    """
    from . import _zone_entities as _impl

    return _impl(hass, runtime)


def _number_entity(hass: HomeAssistant, runtime: ZoneRuntime) -> str | None:
    """The zone's target-illuminance number entity, via the registry."""
    registry = er.async_get(hass)
    for entry_entity in er.async_entries_for_config_entry(
        registry, runtime.entry_id
    ):
        if entry_entity.platform == "number":
            return entry_entity.entity_id
    return None


def _finite_or_none(value, ndigits: int) -> float | None:
    """Round for JSON; non-finite scalars become None instead of poisoning
    the whole overview payload with NaN/Infinity literals (LX-F-006 — the
    browser's JSON.parse would reject the response and every zone's page
    would fail with a misleading format error)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return round(f, ndigits) if math.isfinite(f) else None


def _serialize_curve(curve) -> dict | None:
    """Curve → JSON-safe dict; non-finite points are dropped, not smoothed.

    A curve cleaned down to fewer than 2 points is indistinguishable from
    "not calibrated" for plotting purposes — serialize as None so the page
    shows one consistent empty state (and the button says 开始校准, not the
    contradictory 重新校准).
    """
    if curve is None:
        return None
    points: list[list[float]] = []
    for pct, lux in curve.points:
        p = _finite_or_none(pct, 1)
        v = _finite_or_none(lux, 2)
        if p is None or v is None:
            continue
        points.append([p, v])
    if len(points) < 2:
        return None
    max_lux = _finite_or_none(curve.max_lux, 1)
    if max_lux is None:
        # Scalar cleaned away while the point list survived (LX-F-026):
        # recompute from the surviving points instead of shipping nulls the
        # page would plot as garbage.
        max_lux = max(v for _, v in points)
    slope = _finite_or_none(curve.slope_20_80, 2)
    if slope is None:
        by_pct = dict(points)
        p20, p80 = by_pct.get(20.0), by_pct.get(80.0)
        if p20 is not None and p80 is not None:
            slope = round((p80 - p20) / 60.0, 2)
    return {
        "source": curve.source,
        "max_lux": max_lux,
        "slope_20_80": slope,
        "points": points,
    }


def _serialize_zone(hass: HomeAssistant, runtime: ZoneRuntime) -> dict:
    """One zone snapshot; plain attribute reads, no I/O, safe in a handler."""
    last = runtime.last_decision
    last_adjustment = (
        dt_util.as_local(runtime.last_adjustment).isoformat()
        if runtime.last_adjustment
        else None
    )
    return {
        "entry_id": runtime.entry_id,
        "zone_name": runtime.zone_name,
        "mode": runtime.mode,
        "cal_progress": runtime.cal_progress,
        "target_lux": _finite_or_none(runtime.target_lux, 1),
        "commanded_pct": (
            _finite_or_none(runtime.commanded_pct, 1)
            if runtime.commanded_pct is not None
            else None
        ),
        "target_min": TARGET_MIN_LUX,
        "target_max": TARGET_MAX_LUX,
        "target_step": TARGET_STEP_LUX,
        "lux_stale": runtime.lux_stale,
        "curve": _serialize_curve(runtime.curve),
        "decisions": list(runtime.decisions),
        "ambient_lux_est": (
            _finite_or_none(last.ambient_lux, 1) if last is not None else None
        ),
        "needed_lux": (
            _finite_or_none(last.needed_lux, 1) if last is not None else None
        ),
        "last_adjustment": last_adjustment,
        "light_entity": runtime.light_entity,
        "lux_entity": runtime.lux_entity,
        "number_entity": _number_entity(hass, runtime),
        "calibrate_entity_ids": sorted(_zone_entities(hass, runtime)),
    }


class OverviewView(HomeAssistantView):
    """GET /api/lux_balance/overview — one snapshot for all zones."""

    url = f"{API_BASE}/overview"
    name = "api:lux_balance:overview"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        runtimes: dict = hass.data.get(DOMAIN) or {}
        zones = [_serialize_zone(hass, rt) for rt in runtimes.values()]
        zones.sort(key=lambda z: z["zone_name"])
        return web.json_response({"zones": zones})


async def async_setup_web(hass: HomeAssistant) -> None:
    """Register static assets and the API view (once per HA run), then the
    page in whichever mode fits (hub registry vs standalone panel)."""
    flags: dict = hass.data.setdefault(WEB_DATA_KEY, {})

    if not flags.get("views"):
        hass.http.register_view(OverviewView())
        flags["views"] = True

    if not flags.get("static"):
        static_dir = Path(__file__).parent / "static"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(static_dir), cache_headers=False)]
        )
        flags["static"] = True

    _register_page(hass, flags)

    if not flags.get("started_recheck"):
        # Load-order race: if this integration set up before the hub, the
        # registry key did not exist yet and we fell back to a standalone
        # panel. Once every entry is loaded, re-check once and switch.
        flags["started_recheck"] = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _make_started_recheck(hass, flags)
        )


def _make_started_recheck(hass: HomeAssistant, flags: dict):
    @callback
    def _recheck(event: Event) -> None:
        _LOGGER.debug("HA started: re-checking page registration mode")
        _register_page(hass, flags)

    return _recheck


def _register_page(hass: HomeAssistant, flags: dict) -> None:
    """(Re-)register the page in whichever mode fits right now.

    Re-evaluated on every setup and at HA started: the hub probe is the
    registry key's existence, which the hub keeps truthful (created in its
    async_setup_entry, deleted when the hub entry is removed — the
    FumihaHub registry lifetime contract). A mode switch tears the old
    registration down first, so removing the hub entry and reloading this
    integration restores the standalone panel without a HA restart.
    """
    mode = "hub" if REGISTRY_KEY in hass.data else "standalone"
    current = flags.get("page_registered")
    if current == mode:
        return
    if current is not None:
        _teardown_page(hass, flags)

    if mode == "hub":
        registry = hass.data.setdefault(REGISTRY_KEY, {})
        if PAGE_ID not in registry:
            registry[PAGE_ID] = _descriptor(hass)
            hass.bus.async_fire(
                BUS_EVENT_PAGE_CHANGED, {"id": PAGE_ID, "action": "register"}
            )
            _LOGGER.info("亮度均衡页面已注册到文羽面板壳")
        flags["page_registered"] = "hub"
        return

    panels = hass.data.get(frontend.DATA_PANELS) or {}
    if STANDALONE_PANEL_URL_PATH not in panels:
        version = _manifest_version(hass)
        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            frontend_url_path=STANDALONE_PANEL_URL_PATH,
            sidebar_title=PAGE_TITLE,
            sidebar_icon=PAGE_ICON,
            config={
                "_panel_custom": {
                    "name": PAGE_ELEMENT,
                    "embed_iframe": False,
                    "trust_external": False,
                    "module_url": f"{URL_BASE}/page.js?ver={version}",
                }
            },
            require_admin=True,
        )
        _LOGGER.info("未检测到文羽面板壳，亮度均衡页面注册为独立侧边栏面板")
    flags["page_registered"] = "standalone"


def _teardown_page(hass: HomeAssistant, flags: dict) -> None:
    """Remove the current registration (hub descriptor or standalone panel)."""
    mode = flags.pop("page_registered", None)
    if mode == "hub":
        registry = hass.data.get(REGISTRY_KEY)
        if registry is not None and registry.pop(PAGE_ID, None) is not None:
            hass.bus.async_fire(
                BUS_EVENT_PAGE_CHANGED, {"id": PAGE_ID, "action": "unregister"}
            )
    elif mode == "standalone":
        frontend.async_remove_panel(
            hass, STANDALONE_PANEL_URL_PATH, warn_if_unknown=False
        )


@callback
def async_unload_web(hass: HomeAssistant) -> None:
    """Unregister the page when the LAST zone goes away; views/static stay."""
    if hass.data.get(DOMAIN):
        return  # other zones still use the page
    flags: dict = hass.data.get(WEB_DATA_KEY) or {}

    unsub = flags.pop("started_recheck", None)
    if unsub is not None:
        unsub()

    _teardown_page(hass, flags)
