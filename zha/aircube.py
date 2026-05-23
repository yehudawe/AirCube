"""StuckAtPrototype AirCube air quality monitor quirk for ZHA."""

from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import QuirkBuilder
from zigpy.quirks.v2.homeassistant import EntityType
from zigpy.zcl.foundation import ZCLAttributeDef
import zigpy.types as t

try:
    from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass, SensorStateClass
except ImportError:
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass


class AirQualityCluster(CustomCluster):
    """AirCube custom air quality cluster (0xFC01) — read-only sensors."""

    cluster_id = 0xFC01
    name = "AirCube Air Quality"
    ep_attribute = "aircube_air_quality"

    class AttributeDefs(CustomCluster.AttributeDefs):
        eco2 = ZCLAttributeDef(
            id=0x0000, type=t.uint16_t, is_manufacturer_specific=False
        )
        etvoc = ZCLAttributeDef(
            id=0x0001, type=t.uint16_t, is_manufacturer_specific=False
        )
        # Legacy ENS161 relative AQI-S (0-500). Kept on attribute 0x0002 so
        # existing Home Assistant / Zigbee2MQTT installs continue to work.
        aqi_s = ZCLAttributeDef(
            id=0x0002, type=t.uint16_t, is_manufacturer_specific=False
        )
        # Canonical AirCube AQI (TVOC-derived, 0-400) added in firmware 1.5.0.
        # This is the value that tracks the LED color.
        aqi = ZCLAttributeDef(
            id=0x0003, type=t.uint16_t, is_manufacturer_specific=False
        )


ANALOG_OUTPUT_CLUSTER_ID = 0x000D

(
    QuirkBuilder("StuckAtPrototype", "AirCube")
    .replaces(AirQualityCluster, endpoint_id=10)
    .sensor(
        AirQualityCluster.AttributeDefs.eco2.name,
        AirQualityCluster.cluster_id,
        endpoint_id=10,
        unit="ppm",
        translation_key="equivalent_co2",
        state_class=SensorStateClass.MEASUREMENT,
        fallback_name="Equivalent CO2",
    )
    .sensor(
        AirQualityCluster.AttributeDefs.etvoc.name,
        AirQualityCluster.cluster_id,
        endpoint_id=10,
        unit="ppb",
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        state_class=SensorStateClass.MEASUREMENT,
        fallback_name="Volatile organic compounds",
    )
    .sensor(
        AirQualityCluster.AttributeDefs.aqi.name,
        AirQualityCluster.cluster_id,
        endpoint_id=10,
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
        fallback_name="Air quality index",
    )
    .sensor(
        AirQualityCluster.AttributeDefs.aqi_s.name,
        AirQualityCluster.cluster_id,
        endpoint_id=10,
        translation_key="aqi_s",
        state_class=SensorStateClass.MEASUREMENT,
        fallback_name="Air quality index (relative, AQI-S)",
    )
    .number(
        "present_value",
        ANALOG_OUTPUT_CLUSTER_ID,
        endpoint_id=10,
        min_value=0,
        max_value=100,
        step=1,
        mode="slider",
        entity_type=EntityType.STANDARD,
        translation_key="brightness",
        fallback_name="Brightness",
    )
    .add_to_registry()
)
