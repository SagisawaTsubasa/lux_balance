"""Config flow: one entry per constant-illuminance zone."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_TURN_OFF,
    CONF_CAL_STEP_PCT,
    CONF_DEADBAND_PCT,
    CONF_LIGHT_ENTITY,
    CONF_LUX_ENTITY,
    CONF_MANUAL_SLOPE,
    CONF_MIN_BRIGHTNESS_PCT,
    CONF_SCAN_INTERVAL_S,
    CONF_TARGET_LUX,
    CONF_ZONE_NAME,
    DEFAULT_AUTO_TURN_OFF,
    DEFAULT_CAL_STEP_PCT,
    DEFAULT_DEADBAND_PCT,
    DEFAULT_MANUAL_SLOPE,
    DEFAULT_MIN_BRIGHTNESS_PCT,
    DEFAULT_SCAN_INTERVAL_S,
    DEFAULT_TARGET_LUX,
    DOMAIN,
)

# Color modes that imply the light can dim (anything but plain on/off).
_BRIGHTNESS_MODES = {
    "brightness",
    "color_temp",
    "hs",
    "rgb",
    "rgbw",
    "rgbww",
    "xy",
    "white",
}


def merged_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Options merged over defaults; single source of truth for runtime too."""
    return {
        CONF_TARGET_LUX: options.get(CONF_TARGET_LUX, DEFAULT_TARGET_LUX),
        CONF_SCAN_INTERVAL_S: options.get(
            CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S
        ),
        CONF_DEADBAND_PCT: options.get(CONF_DEADBAND_PCT, DEFAULT_DEADBAND_PCT),
        CONF_MIN_BRIGHTNESS_PCT: options.get(
            CONF_MIN_BRIGHTNESS_PCT, DEFAULT_MIN_BRIGHTNESS_PCT
        ),
        CONF_CAL_STEP_PCT: options.get(CONF_CAL_STEP_PCT, DEFAULT_CAL_STEP_PCT),
        CONF_AUTO_TURN_OFF: options.get(CONF_AUTO_TURN_OFF, DEFAULT_AUTO_TURN_OFF),
        CONF_MANUAL_SLOPE: options.get(CONF_MANUAL_SLOPE, DEFAULT_MANUAL_SLOPE),
    }


def _user_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ZONE_NAME): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Required(CONF_LIGHT_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light")
            ),
            vol.Required(CONF_LUX_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
        }
    )


class LuxBalanceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the per-zone config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LuxBalanceOptionsFlow:
        """Create the options flow handler."""
        return LuxBalanceOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            light_entity: str = user_input[CONF_LIGHT_ENTITY]
            lux_entity: str = user_input[CONF_LUX_ENTITY]
            state = self.hass.states.get(light_entity)
            registry_entry = er.async_get(self.hass).async_get(light_entity)
            if state is None:
                errors["base"] = "entity_missing"
            elif registry_entry is not None and registry_entry.platform == DOMAIN:
                errors["base"] = "light_is_virtual"
            elif not _BRIGHTNESS_MODES & set(
                state.attributes.get("supported_color_modes") or []
            ):
                errors["base"] = "light_no_brightness"
            else:
                await self.async_set_unique_id(f"{light_entity}::{lux_entity}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=str(user_input[CONF_ZONE_NAME]), data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_user_schema(), user_input),
            errors=errors,
        )


class LuxBalanceOptionsFlow(config_entries.OptionsFlow):
    """Runtime-tunable options for one zone."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = merged_options(self._entry.options)
        schema = vol.Schema(
            {
                vol.Required(CONF_TARGET_LUX): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=500,
                        step=5,
                        unit_of_measurement="lx",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Required(CONF_SCAN_INTERVAL_S): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=300, step=5, unit_of_measurement="s"
                    )
                ),
                vol.Required(CONF_DEADBAND_PCT): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=20, step=1, unit_of_measurement="%"
                    )
                ),
                vol.Required(CONF_MIN_BRIGHTNESS_PCT): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=50, step=1, unit_of_measurement="%"
                    )
                ),
                vol.Required(CONF_CAL_STEP_PCT): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=2, max=20, step=1, unit_of_measurement="%"
                    )
                ),
                vol.Required(CONF_AUTO_TURN_OFF): selector.BooleanSelector(),
                vol.Required(CONF_MANUAL_SLOPE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=10,
                        step=0.1,
                        unit_of_measurement="lx/%",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
        )
