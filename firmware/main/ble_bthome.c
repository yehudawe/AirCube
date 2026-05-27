/**
 * @file ble_bthome.c
 * @brief BLE BTHome v2 broadcaster for AirCube
 *
 * Builds a non-connectable BLE advertisement in BTHome v2 format and
 * updates it whenever sensor_task calls ble_bthome_update(). Home
 * Assistant's Bluetooth integration auto-discovers the device through
 * any nearby Bluetooth proxy.
 *
 * BTHome v2 spec: https://bthome.io/format/
 *
 * Advertisement layout:
 *   AD[0] Flags (0x01)            : 0x06
 *   AD[1] Service Data (0x16)     : UUID 0xFCD2 + device info + objects
 *   Scan Response: Complete Local Name (0x09) : "AirCube"
 *
 * BTHome service data payload (object IDs must be in ascending order):
 *   0x40            device info byte (no encryption, v2)
 *   0x02  sint16    temperature * 100 (°C)
 *   0x03  uint16    humidity    * 100 (%)
 *   0x12  uint16    eCO2 (ppm)
 *   0x13  uint16    eTVOC (ppb — BTHome labels unit as µg/m³)
 */

#include "ble_bthome.h"

#include <string.h>
#include "esp_log.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_gap.h"

static const char *TAG = "ble_bthome";

// BTHome v2 service UUID: 0xFCD2
#define BTHOME_UUID_LSB     0xD2
#define BTHOME_UUID_MSB     0xFC
// Device info: no encryption (bit 0 = 0), BTHome version 2 (bits 7:5 = 010)
#define BTHOME_DEVICE_INFO  0x40

// Object IDs — must appear in ascending order in the payload
#define BTHOME_OBJ_TEMPERATURE  0x02  // sint16 * 0.01 °C
#define BTHOME_OBJ_HUMIDITY     0x03  // uint16 * 0.01 %
#define BTHOME_OBJ_CO2          0x12  // uint16 ppm
#define BTHOME_OBJ_TVOC         0x13  // uint16 µg/m³ (we send ppb)

static bool     s_ble_ready  = false;
static int16_t  s_temp_x100  = 2000;  // 20.00 °C until first update
static uint16_t s_hum_x100   = 5000;  // 50.00 %
static uint16_t s_co2        = 0;
static uint16_t s_tvoc       = 0;

// ---------------------------------------------------------------------------
// Advertising helpers
// ---------------------------------------------------------------------------

static void do_advertise(void)
{
    // ── Build advertisement payload ──────────────────────────────────────
    uint8_t adv[31];
    int pos = 0;

    // AD: Flags
    adv[pos++] = 2;
    adv[pos++] = 0x01;
    adv[pos++] = 0x06;  // LE General Discoverable | BR/EDR Not Supported

    // BTHome v2 service data (UUID + device info + objects)
    uint8_t svc[20];
    int sp = 0;
    svc[sp++] = BTHOME_UUID_LSB;
    svc[sp++] = BTHOME_UUID_MSB;
    svc[sp++] = BTHOME_DEVICE_INFO;

    int16_t t = s_temp_x100;
    svc[sp++] = BTHOME_OBJ_TEMPERATURE;
    svc[sp++] = (uint8_t)((uint16_t)t & 0xFF);
    svc[sp++] = (uint8_t)((uint16_t)t >> 8);

    svc[sp++] = BTHOME_OBJ_HUMIDITY;
    svc[sp++] = (uint8_t)(s_hum_x100 & 0xFF);
    svc[sp++] = (uint8_t)(s_hum_x100 >> 8);

    svc[sp++] = BTHOME_OBJ_CO2;
    svc[sp++] = (uint8_t)(s_co2 & 0xFF);
    svc[sp++] = (uint8_t)(s_co2 >> 8);

    svc[sp++] = BTHOME_OBJ_TVOC;
    svc[sp++] = (uint8_t)(s_tvoc & 0xFF);
    svc[sp++] = (uint8_t)(s_tvoc >> 8);

    // AD: Service Data - 16-bit UUID (type 0x16)
    adv[pos++] = sp + 1;  // length = payload bytes + type byte
    adv[pos++] = 0x16;
    memcpy(adv + pos, svc, sp);
    pos += sp;

    int rc = ble_gap_adv_set_data(adv, pos);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_gap_adv_set_data failed: %d", rc);
        return;
    }

    // ── Scan response: device name ───────────────────────────────────────
    uint8_t rsp[31];
    int rp = 0;
    const char *name = "AirCube";
    uint8_t nlen = (uint8_t)strlen(name);
    rsp[rp++] = nlen + 1;
    rsp[rp++] = 0x09;  // Complete Local Name
    memcpy(rsp + rp, name, nlen);
    rp += nlen;
    ble_gap_adv_rsp_set_data(rsp, rp);

    // ── Start non-connectable advertising ────────────────────────────────
    struct ble_gap_adv_params params = {0};
    params.conn_mode = BLE_GAP_CONN_MODE_NON;
    params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    // 500 – 1000 ms interval: low enough for HA discovery, friendly to Zigbee coex
    params.itvl_min  = BLE_GAP_ADV_ITVL_MS(500);
    params.itvl_max  = BLE_GAP_ADV_ITVL_MS(1000);

    rc = ble_gap_adv_start(BLE_OWN_ADDR_PUBLIC, NULL, BLE_HS_FOREVER,
                           &params, NULL, NULL);
    if (rc != 0 && rc != BLE_HS_EALREADY) {
        ESP_LOGE(TAG, "ble_gap_adv_start failed: %d", rc);
    }
}

// ---------------------------------------------------------------------------
// NimBLE host callbacks
// ---------------------------------------------------------------------------

static void on_sync(void)
{
    s_ble_ready = true;
    ESP_LOGI(TAG, "BLE stack ready — starting BTHome advertising");
    do_advertise();
}

static void on_reset(int reason)
{
    s_ble_ready = false;
    ESP_LOGW(TAG, "BLE host reset (reason %d)", reason);
}

// NimBLE host task — runs nimble_port_run() which never returns normally
static void ble_host_task(void *param)
{
    nimble_port_run();
    nimble_port_freertos_deinit();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

void ble_bthome_init(void)
{
    esp_err_t ret = nimble_port_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "nimble_port_init failed: %s", esp_err_to_name(ret));
        return;
    }

    ble_hs_cfg.sync_cb  = on_sync;
    ble_hs_cfg.reset_cb = on_reset;

    nimble_port_freertos_init(ble_host_task);
    ESP_LOGI(TAG, "BLE BTHome module initialized");
}

void ble_bthome_update(float temp_c, float humidity, int eco2, int etvoc)
{
    s_temp_x100 = (int16_t)(temp_c   * 100.0f);
    s_hum_x100  = (uint16_t)(humidity * 100.0f);
    s_co2  = (uint16_t)(eco2  < 65535 ? eco2  : 65535);
    s_tvoc = (uint16_t)(etvoc < 65535 ? etvoc : 65535);

    if (!s_ble_ready) {
        return;
    }

    if (ble_gap_adv_active()) {
        ble_gap_adv_stop();
    }
    do_advertise();
}
