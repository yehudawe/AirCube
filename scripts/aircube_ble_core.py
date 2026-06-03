"""
AirCube BLE core — firmware-faithful BTHome parsing and AQI/color math.

Mirrors the AirCube firmware so other scripts can reuse the same logic:
  - BTHome v2 advertisement parsing (firmware/main/ble_bthome.c)
  - TVOC -> AQI mapping (firmware/main/main.c: aqi_calculate, aqi_tvoc_to_level_pos)
  - AQI -> LED hue -> RGB (firmware/main/main.c: aqi_to_hue,
    firmware/main/led_color_lib.c: get_color_from_hue)

No GUI dependencies — safe to import from any Python project.
"""

from __future__ import annotations

import colorsys

BTHOME_SERVICE_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
AIRCUBE_NAME = "AirCube"

# BTHome v2 objects the AirCube emits (id -> (size_bytes, signed, factor))
_BTHOME_OBJECTS = {
    0x02: (2, True, 0.01),   # temperature C
    0x03: (2, False, 0.01),  # humidity %
    0x12: (2, False, 1),     # eCO2 ppm
    0x13: (2, False, 1),     # eTVOC ppb
}
_BTHOME_KEYS = {
    0x02: "temperature_c",
    0x03: "humidity",
    0x12: "eco2",
    0x13: "etvoc",
}


def parse_bthome(data: bytes) -> dict:
    """Parse AirCube BTHome v2 service data. data[0] is the device-info byte (0x40)."""
    out: dict = {}
    if not data:
        return out
    i = 1  # skip device-info byte
    while i < len(data):
        obj = data[i]
        i += 1
        spec = _BTHOME_OBJECTS.get(obj)
        if spec is None:
            break  # unknown id -> unknown length, stop safely
        size, signed, factor = spec
        raw = int.from_bytes(data[i : i + size], "little", signed=signed)
        i += size
        val = raw * factor
        if isinstance(factor, float):
            out[_BTHOME_KEYS[obj]] = round(val, 2)
        else:
            out[_BTHOME_KEYS[obj]] = val
    return out


# --- AQI from TVOC (mirrors aqi_calculate / aqi_tvoc_to_level_pos in main.c) ---
AQI_TVOC_THRESHOLDS_PPB = [65, 220, 650, 2200, 5500]
BAND_AQI_TVOC = [0, 15, 50, 100, 200, 500]


def tvoc_to_level_pos(value: float) -> float:
    if value <= 0:
        return 0.0
    if value >= AQI_TVOC_THRESHOLDS_PPB[4]:
        return 5.0
    if value < AQI_TVOC_THRESHOLDS_PPB[0]:
        return value / AQI_TVOC_THRESHOLDS_PPB[0]
    for i in range(4):
        if value < AQI_TVOC_THRESHOLDS_PPB[i + 1]:
            span = AQI_TVOC_THRESHOLDS_PPB[i + 1] - AQI_TVOC_THRESHOLDS_PPB[i]
            frac = (value - AQI_TVOC_THRESHOLDS_PPB[i]) / span
            return (i + 1) + frac
    return 5.0


def aqi_from_tvoc(etvoc: float) -> int:
    pos = tvoc_to_level_pos(etvoc)
    if pos <= 0.0:
        return BAND_AQI_TVOC[0]
    if pos >= 5.0:
        return BAND_AQI_TVOC[5]
    low = min(int(pos), 4)
    frac = pos - low
    aqi = BAND_AQI_TVOC[low] + int((BAND_AQI_TVOC[low + 1] - BAND_AQI_TVOC[low]) * frac)
    return max(0, min(500, aqi))


# --- LED color (mirrors aqi_to_hue in main.c + get_color_from_hue in led_color_lib.c) ---
AQI_MIN = 0
AQI_MAX = 200
AQI_GREEN_THRESHOLD = 10
HUE_GREEN = 21845


def aqi_to_hue(aqi: int) -> int:
    aqi = max(AQI_MIN, min(AQI_MAX, aqi))
    if aqi <= AQI_GREEN_THRESHOLD:
        return HUE_GREEN
    ratio = (aqi - AQI_GREEN_THRESHOLD) / (AQI_MAX - AQI_GREEN_THRESHOLD)
    return int(HUE_GREEN - ratio * HUE_GREEN)


def hue16_to_rgb(hue16: int) -> tuple[int, int, int]:
    # Firmware uses S=V=1 HSV->RGB; LED brightness is separate, so swatch = full value.
    r, g, b = colorsys.hsv_to_rgb(hue16 / 65536.0, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def aqi_to_rgb(aqi: int) -> tuple[int, int, int]:
    return hue16_to_rgb(aqi_to_hue(aqi))


def aqi_to_hex(aqi: int) -> str:
    r, g, b = aqi_to_rgb(aqi)
    return f"#{r:02x}{g:02x}{b:02x}"


def aqi_rating(aqi: int) -> str:
    if aqi < 15:
        return "Excellent"
    if aqi < 50:
        return "Good"
    if aqi < 100:
        return "Moderate"
    if aqi < 200:
        return "Poor"
    return "Unhealthy"


def is_aircube_advertisement(adv) -> bool:
    """True if a bleak AdvertisementData looks like an AirCube (BTHome UUID present)."""
    sd = getattr(adv, "service_data", None) or {}
    if BTHOME_SERVICE_UUID in sd:
        return True
    name = getattr(adv, "local_name", None) or ""
    return name.startswith(AIRCUBE_NAME)


def get_bthome_payload(adv) -> bytes | None:
    sd = getattr(adv, "service_data", None) or {}
    return sd.get(BTHOME_SERVICE_UUID)
