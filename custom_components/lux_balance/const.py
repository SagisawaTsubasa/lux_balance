"""Constants for the lux_balance integration."""

DOMAIN = "lux_balance"
PLATFORMS = ["light", "number", "button", "sensor"]

# config entry data keys
CONF_ZONE_NAME = "zone_name"
CONF_LIGHT_ENTITY = "light_entity"
CONF_LUX_ENTITY = "lux_entity"

# options keys
CONF_TARGET_LUX = "target_lux"
CONF_SCAN_INTERVAL_S = "scan_interval_s"
CONF_DEADBAND_PCT = "deadband_pct"
CONF_MIN_BRIGHTNESS_PCT = "min_brightness_pct"
CONF_CAL_STEP_PCT = "calibrate_step_pct"
CONF_AUTO_TURN_OFF = "auto_turn_off"
CONF_MANUAL_SLOPE = "manual_slope"

DEFAULT_TARGET_LUX = 150.0
DEFAULT_SCAN_INTERVAL_S = 45
DEFAULT_DEADBAND_PCT = 5.0
DEFAULT_MIN_BRIGHTNESS_PCT = 5.0
DEFAULT_CAL_STEP_PCT = 5
DEFAULT_AUTO_TURN_OFF = False
DEFAULT_MANUAL_SLOPE = 0.0

# runtime modes (also used as sensor state values, keep lowercase)
MODE_IDLE = "idle"
MODE_ACTIVE = "active"
MODE_CALIBRATING = "calibrating"
MODE_PASSTHROUGH = "passthrough"

# calibration timing (per DESIGN.md §5.1, grounded in 2026-09-25 measurements)
CAL_FIRST_REPORT_TIMEOUT_S = 60
CAL_QUIET_PERIOD_S = 20
CAL_CMD_SETTLE_S = 2
CAL_POLL_INTERVAL_S = 1
CAL_TIMEOUT_UPGRADE_STREAK = 2
CAL_MIN_STEP_PCT = 2
CAL_MIN_USEFUL_LUX = 5.0  # calibrated curve below this is treated as no response

DECISION_RING_SIZE = 50

SERVICE_CALIBRATE = "calibrate"
