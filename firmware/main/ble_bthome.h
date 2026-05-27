/**
 * @file ble_bthome.h
 * @brief BLE BTHome v2 broadcaster for AirCube
 *
 * Advertises temperature, humidity, eCO2, and eTVOC in BTHome v2 format
 * (service UUID 0xFCD2) so Home Assistant's Bluetooth integration
 * auto-discovers the device through a nearby Bluetooth proxy.
 *
 * Non-connectable broadcast only — no pairing, no GATT server.
 * Coexists with the Zigbee stack via ESP-IDF's software coexistence module.
 */

#ifndef BLE_BTHOME_H
#define BLE_BTHOME_H

#include <stdint.h>

/**
 * @brief Initialize the NimBLE stack and start BTHome advertising.
 *
 * Must be called after nvs_flash_init(). Starts advertising immediately
 * once the BLE stack is synchronized (a few hundred milliseconds after
 * this call returns). Safe to call alongside zigbee_init().
 */
void ble_bthome_init(void);

/**
 * @brief Update the advertised sensor values.
 *
 * Rebuilds the BTHome payload and restarts advertising with the new data.
 * No-op until the BLE stack has completed initialization.
 * @param temp_c   Temperature in °C (after offset correction)
 * @param humidity Relative humidity in % (0-100)
 * @param eco2     Equivalent CO2 in ppm
 * @param etvoc    Equivalent TVOC in ppb (advertised in BTHome TVOC slot;
 *                 HA labels the unit as µg/m³, values are ppb)
 */
void ble_bthome_update(float temp_c, float humidity, int eco2, int etvoc);

#endif // BLE_BTHOME_H
