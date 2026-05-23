/**
 * Zigbee2MQTT External Converter for AirCube (Z2M 2.x)
 *
 * Z2M 2.x requires ES module format (.mjs). For Z2M 1.x, use aircube.js instead.
 *
 * Place this file in your Zigbee2MQTT external_converters directory and
 * reference it in configuration.yaml:
 *
 *   external_converters:
 *     - external_converters/aircube.mjs
 *
 * Custom cluster 0xFC01 attributes (matches zha/aircube.py):
 *   0x0000 = eco2     (uint16, ppm)
 *   0x0001 = etvoc    (uint16, ppb)
 *   0x0002 = aqi      (uint16, AQI-S relative, 0-500 — all firmware)
 *   0x0003 = aqi_tvoc (uint16, TVOC-derived AQI, 0-400 — firmware 1.5.0+)
 */

import {temperature, humidity} from 'zigbee-herdsman-converters/lib/modernExtend';
import * as exposes from 'zigbee-herdsman-converters/lib/exposes';

const e = exposes.presets;

// Z2M 2.x requires the cluster ID as a string for custom (non-standard) clusters.
const CUSTOM_CLUSTER_ID = '64513'; // 0xFC01

const ATTR_ECO2     = 0x0000;
const ATTR_ETVOC    = 0x0001;
const ATTR_AQI      = 0x0002;   // AQI-S (relative); wire name "aqi" in ZHA quirk
const ATTR_AQI_TVOC = 0x0003;   // TVOC-derived AQI (firmware 1.5.0+)

const fzAirCubeAirQuality = {
    cluster: CUSTOM_CLUSTER_ID,
    type: ['attributeReport', 'readResponse'],
    convert: (model, msg, publish, options, meta) => {
        const result = {};
        if (msg.data.hasOwnProperty(ATTR_ECO2)) {
            result.eco2 = msg.data[ATTR_ECO2];
        }
        if (msg.data.hasOwnProperty(ATTR_ETVOC)) {
            result.voc = msg.data[ATTR_ETVOC];
        }
        if (msg.data.hasOwnProperty(ATTR_AQI)) {
            result.aqi_s = msg.data[ATTR_AQI];
        }
        if (msg.data.hasOwnProperty(ATTR_AQI_TVOC)) {
            result.aqi_tvoc = msg.data[ATTR_AQI_TVOC];
        }
        return result;
    },
};

const fzBrightness = {
    cluster: 'genAnalogOutput',
    type: ['attributeReport', 'readResponse'],
    convert: (model, msg, publish, options, meta) => {
        if (msg.data.hasOwnProperty('presentValue')) {
            return { brightness: Math.round(msg.data['presentValue']) };
        }
    },
};

const tzBrightness = {
    key: ['brightness'],
    convertSet: async (entity, key, value, meta) => {
        const clamped = Math.min(100, Math.max(0, value));
        await entity.write('genAnalogOutput', { presentValue: clamped });
        return { state: { brightness: clamped } };
    },
    convertGet: async (entity, key, meta) => {
        await entity.read('genAnalogOutput', ['presentValue']);
    },
};

const definition = {
    zigbeeModel: ['AirCube'],
    model: 'AirCube',
    vendor: 'StuckAtPrototype',
    description: 'AirCube air quality monitor',
    extend: [
        temperature(),
        humidity(),
    ],
    fromZigbee: [fzAirCubeAirQuality, fzBrightness],
    toZigbee: [tzBrightness],
    exposes: [
        e.numeric('eco2', exposes.access.STATE)
            .withUnit('ppm')
            .withDescription('Equivalent CO2')
            .withValueMin(400)
            .withValueMax(8192),
        e.numeric('voc', exposes.access.STATE)
            .withUnit('ppb')
            .withDescription('tVOC')
            .withValueMin(0)
            .withValueMax(65535),
        e.numeric('aqi_s', exposes.access.STATE)
            .withUnit('')
            .withDescription('AQI-S (relative)')
            .withValueMin(0)
            .withValueMax(500),
        e.numeric('aqi_tvoc', exposes.access.STATE)
            .withUnit('')
            .withDescription('AQI (TVOC)')
            .withValueMin(0)
            .withValueMax(400),
        e.numeric('brightness', exposes.access.ALL)
            .withUnit('%')
            .withDescription('Brightness')
            .withValueMin(0)
            .withValueMax(100),
    ],
    configure: async (device, coordinatorEndpoint) => {
        const endpoint = device.getEndpoint(10);
        await endpoint.bind('msTemperatureMeasurement', coordinatorEndpoint);
        await endpoint.bind('msRelativeHumidity', coordinatorEndpoint);
        await endpoint.configureReporting('msTemperatureMeasurement', [{
            attribute: 'measuredValue', minimumReportInterval: 1,
            maximumReportInterval: 60, reportableChange: 50,
        }]);
        await endpoint.configureReporting('msRelativeHumidity', [{
            attribute: 'measuredValue', minimumReportInterval: 1,
            maximumReportInterval: 60, reportableChange: 100,
        }]);
        await endpoint.bind('genAnalogOutput', coordinatorEndpoint);
        await endpoint.configureReporting('genAnalogOutput', [{
            attribute: 'presentValue', minimumReportInterval: 1,
            maximumReportInterval: 60, reportableChange: 5,
        }]);
    },
};

export default definition;
