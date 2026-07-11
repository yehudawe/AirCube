# AirCircle — DIY AirCube Fork

**A maker remix of [AirCube](https://github.com/StuckAtPrototype/AirCube) by [StuckAtPrototype](https://stuckatprototype.com).**

This repository is a **personal fork**, not the official AirCube project. It adapts the open-source AirCube firmware for a low-cost DIY build using AliExpress parts, and adds a custom **AirCircle** 3D-printed enclosure.

| | |
|---|---|
| **Upstream project** | [StuckAtPrototype/AirCube](https://github.com/StuckAtPrototype/AirCube) |
| **License** | [Apache 2.0](LICENSE) (same as upstream) |
| **Detailed build notes** | [DIY_SUPERMINI.md](DIY_SUPERMINI.md) |

---

## What this fork adds

- **AirCircle enclosure** — custom round case (`mechanical/air-circle/`)
- **ESP32-H2 SuperMini** pin mapping via `firmware/main/board_config.h`
- **ENS160 + AHT21** sensor support (instead of the official ENS161 + ENS210)
- **External WS2812 LED ring** on GPIO4 (instead of the onboard PCB LED)
- **DIY build guide** — sourcing, printing, wiring, and flashing

Firmware still provides air-quality monitoring with a color LED ring, USB serial readings, and **Zigbee / Home Assistant** support from the original AirCube project.

> **Not affiliated with or endorsed by StuckAtPrototype.**

---

## What you need

### Electronics

Example AliExpress listings (verify the correct variant before ordering):

| Part | Notes | Link |
|------|-------|------|
| **ESP32-H2 SuperMini** | Must be the **H2** variant (Zigbee-capable) | [AliExpress](https://a.aliexpress.com/_c4Pyot8F) |
| **ENS160 + AHT21 module** | Combined gas + temperature/humidity sensor | [AliExpress](https://a.aliexpress.com/_c32NbwfH) |
| **WS2812 RGB LED ring** | Match LED count to your ring (e.g. 16-LED) | [AliExpress](https://a.aliexpress.com/_c4Vc3oaj) |

You also need a **USB data cable** for power and flashing.

### 3D-printed parts

Print files are in [`mechanical/air-circle/`](mechanical/air-circle/):

| File | Purpose |
|------|---------|
| `air_circ_base.stl` | Bottom shell |
| `air_circ_top.stl` | Translucent top cover |
| `air_circ_lock.stl` | Retention / lock piece |
| `air_circle.stp` | Full assembly source (CAD edits) |

Original StuckAtPrototype enclosure files are preserved in [`mechanical/original/`](mechanical/original/) for reference only.

---

## Step 1 — Print the enclosure

1. Slice the three STL files in your preferred slicer (Bambu Studio, PrusaSlicer, Cura, etc.).
2. **Material:** PLA or PETG both work. PETG is more heat-tolerant near the electronics.
3. **Top cover:** use a **translucent / natural** filament so the LED ring glows through.
4. **Orientation:** print flat on the bed, largest face down. Add supports only if your slicer flags overhangs that need them.
5. After printing, dry-fit base + top + lock before wiring. Sand or trim only if parts bind.

If your LED ring is a different diameter, you may need to scale the STLs or edit `air_circle.stp`.

---

## Step 2 — Wire the hardware

All logic signals are **3.3 V**. Do not apply 5 V to the sensor data lines or LED data pin.

| Module pin | Connect to ESP32-H2 SuperMini |
|------------|-------------------------------|
| SDA | **GPIO1** (IO1) |
| SCL | **GPIO0** (IO0) |
| VCC | **3V3** |
| GND | **GND** |
| LED DIN | **GPIO4** (IO4) |
| LED +5V | **5V** (USB) — only if your ring needs 5 V power |
| LED GND | **GND** |

Both ENS160 (`0x52`) and AHT21 (`0x38`) share the same I2C bus.

**Button (GPIO9):** the SuperMini boot button is used by the firmware — short press cycles brightness, hold **3 seconds** for Zigbee pairing (blue flash).

```
  ENS160+AHT21          ESP32-H2 SuperMini          WS2812 ring
  ─────────────         ──────────────────          ───────────
  SDA  ───────────────► GPIO1
  SCL  ───────────────► GPIO0
  VCC  ───────────────► 3V3
  GND  ───────────────► GND ────────────────────► GND
                        GPIO4 ──────────────────► DIN
                        5V (optional) ──────────► +5V
```

Pin definitions: [`firmware/main/board_config.h`](firmware/main/board_config.h)

---

## Step 3 — Configure LED count

Before building firmware, set the number of LEDs to match your ring.

Edit [`firmware/main/ws2812_control.h`](firmware/main/ws2812_control.h):

```c
#define NUM_LEDS  16   // change to match your WS2812 ring or strip
```

Default in this fork is **30**; a typical 16-LED ring should use **16**.

---

## Step 4 — Build and flash firmware

Requires [ESP-IDF v5.3+](https://docs.espressif.com/projects/esp-idf/en/latest/esp32h2/get-started/).

```powershell
cd firmware
idf.py set-target esp32h2
idf.py build
idf.py -p COM9 flash monitor
```

Replace `COM9` with your board's serial port (`COM*` on Windows, `/dev/tty*` on Linux).

On first boot, allow **~3 minutes** for the ENS160 to warm up before readings stabilize.

### Button controls

| Action | Result |
|--------|--------|
| Short press | Cycle LED brightness (off → 10% → 30% → 60% → 100%) |
| Hold 3 seconds | Enter Zigbee pairing mode (blue flash) |

---

## Step 5 — View live readings (optional)

Plug the SuperMini into your PC with a data-capable USB cable:

```powershell
cd scripts
pip install -r requirements.txt
python aircube_app.py
```

Select your COM port and click **Connect**. Temperature, humidity, eCO2, TVOC, and VOC Level appear after warm-up.

---

## Home Assistant (optional)

This fork inherits AirCube's **Zigbee** integration. Pair the device with ZHA or Zigbee2MQTT using the upstream guide:

**[HOME_ASSISTANT.md](HOME_ASSISTANT.md)**

Hold the boot button for 3 seconds to enter pairing mode, then enable permit join on your coordinator.

---

## Differences from official AirCube

| | Official AirCube | This fork (AirCircle) |
|---|---|---|
| Board | Custom PCB | ESP32-H2 SuperMini |
| Gas sensor | ENS161 | ENS160 |
| Temp/humidity | ENS210 | AHT21 |
| LED | Onboard WS2812 | External WS2812 ring on GPIO4 |
| Enclosure | StuckAtPrototype design | AirCircle 3D-printed case |
| BLE BTHome | Supported | Disabled in this fork's defaults |
| AQI-S score | Available over USB serial | Not available (`-1` on ENS160) |

For the commercial product, documentation, and official firmware releases, see **[StuckAtPrototype/AirCube](https://github.com/StuckAtPrototype/AirCube)**.

---

## LED color reference

The LED ring shows air quality as a smooth green-to-red gradient driven by **VOC Level** (TVOC-derived):

| LED color | Air quality |
|-----------|-------------|
| Green | Good |
| Yellow | Moderate |
| Orange | Poor |
| Red | Bad — consider ventilating |
| Flashing blue | Zigbee pairing mode |

Full band tables and legacy firmware notes are in the [upstream README](https://github.com/StuckAtPrototype/AirCube/blob/master/README.md#led-reference).

---

## Troubleshooting

**No serial port detected**
- Use a USB cable that supports data, not charge-only.
- Install [Silicon Labs USB-UART drivers](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers) on Windows if needed.

**Readings wrong right after power-on**
- Normal. Allow ~3 minutes for the ENS160 to warm up.

**LED ring wrong colors or partial ring**
- Check `NUM_LEDS` matches your physical ring.
- Confirm DIN is on **GPIO4** and GND is shared.

**Zigbee won't pair**
- Hold boot button 3 seconds (blue flash).
- Enable permit join in ZHA or Zigbee2MQTT.
- Move the device closer to the coordinator.

**Home Assistant missing sensors**
- Load the custom ZHA quirk or Zigbee2MQTT converter — see [HOME_ASSISTANT.md](HOME_ASSISTANT.md).

---

## Repository layout

```
AirCube/
├── mechanical/
│   ├── air-circle/          # AirCircle enclosure (STL + STEP)
│   └── original/            # Upstream reference enclosure files
├── firmware/                # Adapted ESP-IDF firmware
│   └── main/
│       ├── board_config.h   # SuperMini pin map
│       └── ws2812_control.h # LED count (NUM_LEDS)
├── scripts/                 # Desktop app for USB serial
├── DIY_SUPERMINI.md         # Supplementary build notes
└── HOME_ASSISTANT.md        # Zigbee setup (from upstream)
```

---

## License and attribution

Based on [AirCube](https://github.com/StuckAtPrototype/AirCube) by StuckAtPrototype, licensed under [Apache 2.0](LICENSE).

AirCircle mechanical files and SuperMini adaptations in this fork are shared under the same license. When redistributing, keep the license and credit the original project.
