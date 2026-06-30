//
// Driver for the Sensirion SCD41 CO2 / temperature / humidity sensor.
// Used on the AirCube "Pro" hardware variant.
//

#ifndef AIRCUBE_SCD41_H
#define AIRCUBE_SCD41_H

#include <stdint.h>
#include <stdbool.h>

// Probe for the sensor, and if present start periodic measurement mode.
// Safe to call on hardware that does not have the SCD41 fitted (Base model):
// it will simply mark the sensor as not present.
void scd41_init(void);

// Returns true if the SCD41 was detected during scd41_init().
bool scd41_is_present(void);

// Reads the latest measurement if a new sample is ready.
// Returns true if a fresh, CRC-valid sample was read (cached getters updated).
// Returns false if no new data was ready or the read failed.
bool scd41_read(void);

// Cached values from the most recent successful scd41_read().
uint16_t scd41_get_co2(void);            // CO2 concentration in ppm
float    scd41_get_temperature_c(void);  // temperature in degrees Celsius
float    scd41_get_humidity(void);       // relative humidity in %

#endif // AIRCUBE_SCD41_H
