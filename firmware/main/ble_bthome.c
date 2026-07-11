/**
 * @file ble_bthome.c
 * @brief BLE BTHome v2 broadcaster for AirCube (optional — disabled on DIY builds)
 */

#include "ble_bthome.h"
#include "sdkconfig.h"

#if CONFIG_BT_ENABLED

#include <string.h>
#include "esp_log.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_gap.h"

static const char *TAG = "ble_bthome";

#define BTHOME_UUID_LSB     0xD2
#define BTHOME_UUID_MSB     0xFC
#define BTHOME_DEVICE_INFO  0x40

#define BTHOME_OBJ_TEMPERATURE  0x02
#define BTHOME_OBJ_HUMIDITY     0x03
#define BTHOME_OBJ_CO2          0x12
#define BTHOME_OBJ_TVOC         0x13

static volatile bool     s_ble_ready  = false;
static volatile int16_t  s_temp_x100  = 2000;
static volatile uint16_t s_hum_x100   = 5000;
static volatile uint16_t s_co2        = 0;
static volatile uint16_t s_tvoc       = 0;

static void do_advertise(void)
{
    uint8_t adv[31];
    int pos = 0;

    adv[pos++] = 2;
    adv[pos++] = 0x01;
    adv[pos++] = 0x06;

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

    adv[pos++] = sp + 1;
    adv[pos++] = 0x16;
    memcpy(adv + pos, svc, sp);
    pos += sp;

    int rc = ble_gap_adv_set_data(adv, pos);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_gap_adv_set_data failed: %d", rc);
        return;
    }

    uint8_t rsp[31];
    int rp = 0;
    const char *name = "AirCube";
    uint8_t nlen = (uint8_t)strlen(name);
    rsp[rp++] = nlen + 1;
    rsp[rp++] = 0x09;
    memcpy(rsp + rp, name, nlen);
    rp += nlen;
    ble_gap_adv_rsp_set_data(rsp, rp);

    struct ble_gap_adv_params params = {0};
    params.conn_mode = BLE_GAP_CONN_MODE_NON;
    params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    params.itvl_min  = BLE_GAP_ADV_ITVL_MS(500);
    params.itvl_max  = BLE_GAP_ADV_ITVL_MS(1000);

    rc = ble_gap_adv_start(BLE_OWN_ADDR_PUBLIC, NULL, BLE_HS_FOREVER,
                           &params, NULL, NULL);
    if (rc != 0 && rc != BLE_HS_EALREADY) {
        ESP_LOGE(TAG, "ble_gap_adv_start failed: %d", rc);
    }
}

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

static void ble_host_task(void *param)
{
    nimble_port_run();
    nimble_port_freertos_deinit();
}

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

#else

void ble_bthome_init(void)
{
}

void ble_bthome_update(float temp_c, float humidity, int eco2, int etvoc)
{
    (void)temp_c;
    (void)humidity;
    (void)eco2;
    (void)etvoc;
}

#endif
