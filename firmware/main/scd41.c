//
// Driver for the Sensirion SCD41 CO2 / temperature / humidity sensor.
// Verified against the SCD4x datasheet v1.7 (April 2025).
//

#include "scd41.h"
#include "i2c_driver.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "scd41";

#define SCD41_I2C_ADDRESS 0x62

// 16-bit command words (most significant byte transmitted first)
#define SCD41_CMD_START_PERIODIC      0x21B1
#define SCD41_CMD_READ_MEASUREMENT    0xEC05
#define SCD41_CMD_STOP_PERIODIC       0x3F86
#define SCD41_CMD_GET_DATA_READY      0xE4B8
#define SCD41_CMD_GET_SERIAL_NUMBER   0x3682
#define SCD41_CMD_GET_SENSOR_VARIANT  0x202F

// CRC-8: polynomial 0x31, init 0xFF, no reflection, final XOR 0x00
#define SCD41_CRC8_POLYNOMIAL 0x31
#define SCD41_CRC8_INIT       0xFF

static bool scd41_present = false;

static uint16_t scd41_co2 = 0;
static float scd41_temperature_c = 0.0f;
static float scd41_humidity = 0.0f;

static uint8_t scd41_crc8(const uint8_t *data, int len)
{
    uint8_t crc = SCD41_CRC8_INIT;
    for (int i = 0; i < len; i++) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++) {
            if (crc & 0x80) {
                crc = (uint8_t)((crc << 1) ^ SCD41_CRC8_POLYNOMIAL);
            } else {
                crc = (uint8_t)(crc << 1);
            }
        }
    }
    return crc;
}

// Send a bare 16-bit command word (no parameters).
static esp_err_t scd41_send_command(uint16_t command)
{
    uint8_t buf[2];
    buf[0] = (uint8_t)(command >> 8);
    buf[1] = (uint8_t)(command & 0xFF);
    return i2c_driver_write(SCD41_I2C_ADDRESS, buf, 2);
}

// Send a command, wait for the execution time, then read 'count' words.
// Each word in the response is 2 bytes followed by 1 CRC byte. The CRC of
// every word is verified; words[] receives the decoded 16-bit values.
static esp_err_t scd41_read_words(uint16_t command, uint16_t *words, int count, uint32_t delay_ms)
{
    esp_err_t ret = scd41_send_command(command);
    if (ret != ESP_OK) {
        return ret;
    }

    vTaskDelay(pdMS_TO_TICKS(delay_ms));

    uint8_t buf[3 * 8]; // up to 8 words supported here
    int bytes = count * 3;
    ret = i2c_driver_read_raw(SCD41_I2C_ADDRESS, buf, bytes);
    if (ret != ESP_OK) {
        return ret;
    }

    for (int i = 0; i < count; i++) {
        const uint8_t *word = &buf[i * 3];
        if (scd41_crc8(word, 2) != word[2]) {
            ESP_LOGW(TAG, "CRC mismatch on word %d (cmd 0x%04X)", i, command);
            return ESP_ERR_INVALID_CRC;
        }
        words[i] = (uint16_t)((word[0] << 8) | word[1]);
    }

    return ESP_OK;
}

bool scd41_is_present(void)
{
    return scd41_present;
}

uint16_t scd41_get_co2(void)            { return scd41_co2; }
float    scd41_get_temperature_c(void)  { return scd41_temperature_c; }
float    scd41_get_humidity(void)       { return scd41_humidity; }

void scd41_init(void)
{
    scd41_present = false;

    // The sensor only responds 500 ms after stop_periodic_measurement, and the
    // command itself is only valid from idle/periodic state. Send it first to
    // guarantee a known idle state, then wait the required settling time.
    scd41_send_command(SCD41_CMD_STOP_PERIODIC);
    vTaskDelay(pdMS_TO_TICKS(500));

    // Probe presence by reading the 48-bit serial number (3 CRC-checked words).
    uint16_t serial[3] = {0};
    esp_err_t ret = scd41_read_words(SCD41_CMD_GET_SERIAL_NUMBER, serial, 3, 1);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "SCD41 not detected (serial read: %s)", esp_err_to_name(ret));
        return;
    }

    // Confirm the variant is specifically an SCD41 (bits[15:12] == 0b0001).
    uint16_t variant = 0;
    ret = scd41_read_words(SCD41_CMD_GET_SENSOR_VARIANT, &variant, 1, 1);
    if (ret == ESP_OK) {
        uint8_t variant_code = (variant >> 12) & 0x0F;
        const char *variant_str = (variant_code == 0x0) ? "SCD40" :
                                  (variant_code == 0x1) ? "SCD41" :
                                  (variant_code == 0x5) ? "SCD43" : "unknown";
        ESP_LOGI(TAG, "SCD4x variant: %s (0x%04X)", variant_str, variant);
    }

    ESP_LOGI(TAG, "SCD41 detected, serial: %04X%04X%04X", serial[0], serial[1], serial[2]);

    // Start periodic measurement mode (new sample every 5 s).
    ret = scd41_send_command(SCD41_CMD_START_PERIODIC);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Failed to start periodic measurement: %s", esp_err_to_name(ret));
        return;
    }

    scd41_present = true;
    ESP_LOGI(TAG, "SCD41 initialized in periodic measurement mode");
}

bool scd41_read(void)
{
    if (!scd41_present) {
        return false;
    }

    // Check whether a fresh sample is ready (data ready if the least
    // significant 11 bits of the status word are non-zero).
    uint16_t status = 0;
    esp_err_t ret = scd41_read_words(SCD41_CMD_GET_DATA_READY, &status, 1, 1);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Data-ready check failed: %s", esp_err_to_name(ret));
        return false;
    }
    if ((status & 0x07FF) == 0) {
        // No new data yet (sensor updates every ~5 s).
        return false;
    }

    // Read CO2, temperature and humidity (3 CRC-checked words).
    uint16_t words[3] = {0};
    ret = scd41_read_words(SCD41_CMD_READ_MEASUREMENT, words, 3, 1);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Measurement read failed: %s", esp_err_to_name(ret));
        return false;
    }

    scd41_co2 = words[0];
    scd41_temperature_c = -45.0f + 175.0f * ((float)words[1] / 65535.0f);
    scd41_humidity = 100.0f * ((float)words[2] / 65535.0f);

    return true;
}
