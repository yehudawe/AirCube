//
// Driver for the Vishay VCNL4040 proximity + ambient light sensor.
//
// The VCNL4040 uses 16-bit registers addressed by a command byte. Each register
// transfers as two bytes, low byte first (little endian). Writes are
// [command, LSB, MSB]; reads write the command byte then read 2 bytes back.
//

#include "vcnl4040.h"
#include "i2c_driver.h"
#include "esp_log.h"

static const char *TAG = "vcnl4040";

#define VCNL4040_I2C_ADDRESS 0x60

// Register (command) map
#define VCNL4040_REG_ALS_CONF  0x00  // ALS integration time / persistence / enable
#define VCNL4040_REG_PS_CONF12 0x03  // PS_CONF1 (low) + PS_CONF2 (high)
#define VCNL4040_REG_PS_DATA   0x08  // proximity result
#define VCNL4040_REG_ALS_DATA  0x09  // ambient light result
#define VCNL4040_REG_DEVICE_ID 0x0C  // device ID, expected 0x0186

#define VCNL4040_DEVICE_ID 0x0186

// ALS_IT = 80 ms (ALS_CONF bits[7:6]=00) gives 0.1 lux per count.
#define VCNL4040_LUX_PER_COUNT 0.1f

static bool vcnl4040_present = false;

static uint16_t vcnl4040_proximity = 0;
static uint16_t vcnl4040_ambient = 0;

static esp_err_t vcnl4040_write_reg(uint8_t reg, uint16_t value)
{
    uint8_t buf[3];
    buf[0] = reg;
    buf[1] = (uint8_t)(value & 0xFF);        // low byte first
    buf[2] = (uint8_t)((value >> 8) & 0xFF); // high byte
    return i2c_driver_write(VCNL4040_I2C_ADDRESS, buf, 3);
}

static esp_err_t vcnl4040_read_reg(uint8_t reg, uint16_t *value)
{
    uint8_t data[2] = {0};
    esp_err_t ret = i2c_driver_read(VCNL4040_I2C_ADDRESS, &reg, 1, data, 2);
    if (ret != ESP_OK) {
        return ret;
    }
    *value = (uint16_t)(data[0] | (data[1] << 8)); // little endian
    return ESP_OK;
}

bool vcnl4040_is_present(void)
{
    return vcnl4040_present;
}

uint16_t vcnl4040_get_proximity(void)   { return vcnl4040_proximity; }
uint16_t vcnl4040_get_ambient_raw(void) { return vcnl4040_ambient; }
float    vcnl4040_get_lux(void)         { return (float)vcnl4040_ambient * VCNL4040_LUX_PER_COUNT; }

void vcnl4040_init(void)
{
    vcnl4040_present = false;

    // Probe presence via the device ID register.
    uint16_t id = 0;
    esp_err_t ret = vcnl4040_read_reg(VCNL4040_REG_DEVICE_ID, &id);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "VCNL4040 not detected (ID read: %s)", esp_err_to_name(ret));
        return;
    }
    if (id != VCNL4040_DEVICE_ID) {
        ESP_LOGW(TAG, "VCNL4040 not detected (unexpected ID 0x%04X)", id);
        return;
    }

    // Enable ALS: ALS_CONF = 0x0000 -> ALS_IT = 80 ms, ALS_SD = 0 (powered on).
    ret = vcnl4040_write_reg(VCNL4040_REG_ALS_CONF, 0x0000);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Failed to configure ALS: %s", esp_err_to_name(ret));
        return;
    }

    // Enable PS: PS_CONF1/PS_CONF2 = 0x0000 -> PS_SD = 0 (powered on), defaults.
    ret = vcnl4040_write_reg(VCNL4040_REG_PS_CONF12, 0x0000);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Failed to configure PS: %s", esp_err_to_name(ret));
        return;
    }

    vcnl4040_present = true;
    ESP_LOGI(TAG, "VCNL4040 detected and initialized (ID 0x%04X)", id);
}

void vcnl4040_read(void)
{
    if (!vcnl4040_present) {
        return;
    }

    uint16_t value = 0;
    if (vcnl4040_read_reg(VCNL4040_REG_PS_DATA, &value) == ESP_OK) {
        vcnl4040_proximity = value;
    } else {
        ESP_LOGW(TAG, "Failed to read proximity data");
    }

    if (vcnl4040_read_reg(VCNL4040_REG_ALS_DATA, &value) == ESP_OK) {
        vcnl4040_ambient = value;
    } else {
        ESP_LOGW(TAG, "Failed to read ambient light data");
    }
}
