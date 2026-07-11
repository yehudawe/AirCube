#ifndef BOARD_CONFIG_H
#define BOARD_CONFIG_H

/*
 * ESP32-H2 SuperMini + ENS160/AHT21 breakout + external WS2812 strip
 *
 * Wiring (3.3V logic — do not use 5V on sensor or LED data):
 *   Sensor SDA  -> GPIO1
 *   Sensor SCL  -> GPIO0
 *   Sensor VCC  -> 3V3
 *   Sensor GND  -> GND
 *   LED DIN     -> GPIO4 (IO4 — breadboard pin)
 *   LED 5V      -> 5V (USB) if your strip needs 5V; level-shift data if required
 *   LED GND     -> GND
 *   Boot button -> GPIO9 (onboard, short press = brightness, hold 3s = Zigbee pair)
 */

#define I2C_MASTER_SDA_IO           1
#define I2C_MASTER_SCL_IO           0
#define LED_RMT_TX_GPIO             4
#define BUTTON_GPIO                 9

#endif
