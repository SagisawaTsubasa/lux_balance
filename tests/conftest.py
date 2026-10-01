"""Pytest configuration for the lux_balance integration tests."""

import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "lux_balance"
sys.path.insert(0, str(PACKAGE))
