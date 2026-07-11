
#include "ens210.h"
#include "i2c_driver.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

/* AHT21 temperature/humidity — drop-in for ENS210 on ENS160+AHT21 breakouts */
#define AHT21_I2C_ADDRESS           0x38
#define AHT21_CMD_INIT              0xBE
#define AHT21_CMD_TRIGGER           0xAC
#define AHT21_STATUS_BUSY           0x80
#define AHT21_STATUS_CALIBRATED     0x08

static const char *TAG = "aht21";

uint8_t ens210_t[2];
uint8_t ens210_h[2];

static float temperature_K;
static float temperature_C;
static float temperature_F;
static float humidity_percentage;
static uint8_t ens210_status_byte;

static esp_err_t aht21_write(const uint8_t *data, size_t len)
{
    return i2c_driver_write(AHT21_I2C_ADDRESS, data, len);
}

static esp_err_t aht21_read(uint8_t *data, size_t len)
{
    return i2c_driver_receive(AHT21_I2C_ADDRESS, data, len);
}

static void ens210_pack_compensation(void)
{
    float tin_k = temperature_C + 273.15f;
    uint16_t t_raw = (uint16_t)(tin_k * 64.0f);
    uint16_t h_raw = (uint16_t)(humidity_percentage * 512.0f);

    ens210_t[0] = (uint8_t)(t_raw & 0xFF);
    ens210_t[1] = (uint8_t)((t_raw >> 8) & 0xFF);
    ens210_h[0] = (uint8_t)(h_raw & 0xFF);
    ens210_h[1] = (uint8_t)((h_raw >> 8) & 0xFF);
}

void ens210_get_envir(uint8_t *t, uint8_t *h)
{
    t[0] = ens210_t[0];
    t[1] = ens210_t[1];
    h[0] = ens210_h[0];
    h[1] = ens210_h[1];
}

float ens210_get_temperature(uint8_t type)
{
    switch (type) {
        case 0:
            return temperature_F;
        case 1:
            return temperature_C;
        case 2:
            return temperature_K;
        default:
            return temperature_F;
    }
}

float ens210_get_humidity(void)
{
    return humidity_percentage;
}

uint8_t ens210_get_status(void)
{
    return ens210_status_byte;
}

void ens210_deinit(void)
{
}

void ens210_read_envir(void)
{
    uint8_t trigger[3] = { AHT21_CMD_TRIGGER, 0x33, 0x00 };
    uint8_t data[7] = { 0 };

    if (aht21_write(trigger, sizeof(trigger)) != ESP_OK) {
        ESP_LOGW(TAG, "Failed to trigger measurement");
        ens210_status_byte |= 0x01;
        return;
    }

    vTaskDelay(pdMS_TO_TICKS(80));

    if (aht21_read(data, sizeof(data)) != ESP_OK) {
        ESP_LOGW(TAG, "Failed to read measurement");
        ens210_status_byte |= 0x02;
        return;
    }

    if (data[0] & AHT21_STATUS_BUSY) {
        ESP_LOGW(TAG, "Sensor still busy");
        ens210_status_byte |= 0x04;
        return;
    }

    uint32_t raw_h = ((uint32_t)data[1] << 12) |
                     ((uint32_t)data[2] << 4) |
                     ((uint32_t)(data[3] >> 4));
    uint32_t raw_t = (((uint32_t)(data[3] & 0x0F)) << 16) |
                     ((uint32_t)data[4] << 8) |
                     (uint32_t)data[5];

    humidity_percentage = ((float)raw_h * 100.0f) / 1048576.0f;
    temperature_C = ((float)raw_t * 200.0f / 1048576.0f) - 50.0f;
    temperature_K = temperature_C + 273.15f;
    temperature_F = temperature_C * 1.8f + 32.0f;

    ens210_status_byte = 0;
    ens210_pack_compensation();

    ESP_LOGI(TAG, "%5.1fK %4.1fC %4.1fF  humidity: %.1f%%",
             temperature_K, temperature_C, temperature_F, humidity_percentage);
}

void ens210_init(void)
{
    uint8_t init_cmd[3] = { AHT21_CMD_INIT, 0x08, 0x00 };
    uint8_t status = 0;

    vTaskDelay(pdMS_TO_TICKS(40));

    if (aht21_write(init_cmd, sizeof(init_cmd)) != ESP_OK) {
        ESP_LOGE(TAG, "AHT21 init write failed");
        ens210_status_byte = 0xFF;
        return;
    }

    vTaskDelay(pdMS_TO_TICKS(10));

    if (aht21_read(&status, 1) != ESP_OK) {
        ESP_LOGE(TAG, "AHT21 status read failed");
        ens210_status_byte = 0xFF;
        return;
    }

    if ((status & AHT21_STATUS_CALIBRATED) == 0) {
        ESP_LOGW(TAG, "AHT21 not calibrated (status=0x%02X)", status);
    }

    ens210_status_byte = status;
    ens210_read_envir();
    ESP_LOGI(TAG, "AHT21 initialized, status: 0x%02X", status);
}
