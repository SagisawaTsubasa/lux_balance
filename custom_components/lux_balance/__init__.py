"""The lux_balance integration: constant-illuminance zones for bathrooms."""

from __future__ import annotations

import inspect
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_extract_entity_ids

from .const import DOMAIN, PLATFORMS, SERVICE_CALIBRATE
from .runtime import ZoneRuntime
from .store import ZoneStorage

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)

_TARGET_KEYS = {"entity_id", "device_id", "area_id", "floor_id", "label_id"}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one constant-illuminance zone from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    runtime = ZoneRuntime(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = runtime
    await runtime.async_load()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    runtime.start()
    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a zone; stop every listener, timer and calibration task."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = hass.data.get(DOMAIN) or {}
    runtime: ZoneRuntime | None = data.pop(entry.entry_id, None)
    if runtime is not None:
        await runtime.async_stop()
    if not data and hass.services.has_service(DOMAIN, SERVICE_CALIBRATE):
        hass.services.async_remove(DOMAIN, SERVICE_CALIBRATE)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the stored calibration curve along with the entry."""
    await ZoneStorage(hass, entry.entry_id).async_remove()


def _zone_entities(hass: HomeAssistant, runtime: ZoneRuntime) -> set[str]:
    """Every entity id that belongs to this zone, plus its raw config picks."""
    registry = er.async_get(hass)
    own = {
        entry_entity.entity_id
        for entry_entity in er.async_entries_for_config_entry(
            registry, runtime.entry_id
        )
    }
    own |= {runtime.light_entity, runtime.lux_entity}
    return own


@callback
def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_CALIBRATE):
        return

    async def handle_calibrate(call: ServiceCall) -> None:
        unknown_keys = set(call.data) - _TARGET_KEYS
        if unknown_keys:
            _LOGGER.warning(
                "lux_balance.calibrate: 忽略未知键 %s", sorted(unknown_keys)
            )
        has_target = bool(set(call.data) & _TARGET_KEYS)
        if unknown_keys and not has_target:
            _LOGGER.warning(
                "lux_balance.calibrate: 未识别到有效目标，放弃执行（防误触发全局校准）"
            )
            return
        entity_ids: set[str] = set()
        if has_target:
            # HA ≥2025.12 dropped the leading hass parameter (deprecated shim
            # since then); probe the signature to support both generations.
            if "hass" in inspect.signature(async_extract_entity_ids).parameters:
                entity_ids = set(await async_extract_entity_ids(hass, call))
            else:
                entity_ids = set(await async_extract_entity_ids(call))
        addressed = 0
        for runtime in list((hass.data.get(DOMAIN) or {}).values()):
            if entity_ids and not entity_ids & _zone_entities(hass, runtime):
                continue
            addressed += 1
            if runtime.start_calibration():
                _LOGGER.info("%s: 校准已启动", runtime.zone_name)
            else:
                _LOGGER.info("%s: 校准已在进行中，忽略重复请求", runtime.zone_name)
        if has_target and addressed == 0:
            _LOGGER.warning("lux_balance.calibrate: 目标未命中任何区域")

    hass.services.async_register(
        DOMAIN,
        SERVICE_CALIBRATE,
        handle_calibrate,
        schema=vol.Schema(
            {vol.Optional(ATTR_ENTITY_ID): cv.entity_ids},
            extra=vol.ALLOW_EXTRA,
        ),
    )
