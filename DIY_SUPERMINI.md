# DIY Build — ESP32-H2 SuperMini

AirCube firmware adapted for breadboard builds with an **ENS160 + AHT21** sensor module and an external **WS2812 LED strip**.

## Wiring

| Module pin | Connect to ESP32-H2 SuperMini |
|------------|-------------------------------|
| SDA        | **GPIO1** (IO1)               |
| SCL        | **GPIO0** (IO0)               |
| VCC        | **3V3**                       |
| GND        | **GND**                       |
| LED DIN    | **GPIO4** (IO4)               |
| LED +5V    | **5V** (USB) if your strip needs 5 V |
| LED GND    | **GND**                       |

Both ENS160 (0x52) and AHT21 (0x38) share the same I2C bus.

**Boot button (GPIO9):** short press cycles LED brightness; hold **3 seconds** for Zigbee pairing (blue flash).

## LED strip length

Edit `firmware/main/ws2812_control.h` and change `NUM_LEDS` to match your strip (default **30**).

## Build and flash

Requires [ESP-IDF v5.3+](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/).

```powershell
cd firmware
idf.py set-target esp32h2
idf.py build
idf.py -p COM9 flash monitor
```

## Desktop app

```powershell
cd scripts
pip install -r requirements.txt
python aircube_app.py
```

Select **COM9**, click **Connect** — live temp, humidity, eCO2, TVOC, and VOC Level appear after ~3 minutes warm-up.

## Notes

- **ENS160** is used instead of the official ENS161; AQI-S (relative score) is not available and shows as `-1` over serial.
- **AHT21** replaces the ENS210; temperature/humidity compensation for the gas sensor still works.
- Onboard **GPIO8** WS2812 is unused; the external strip on GPIO4 drives the air-quality color.

Pin definitions live in `firmware/main/board_config.h`.
