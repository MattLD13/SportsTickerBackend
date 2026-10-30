"""Pi storage, assets, and system command boundaries."""

from ticker.six.platform.assets import AssetCoordinator, AssetFetcher, LongTermAssetCache, PersistentAssetStore
from ticker.six.platform.commands import PlatformCommands, SubprocessPlatformCommands, WiFiNetwork
from ticker.six.platform.constants import PANEL_HEIGHT, PANEL_SIZE, PANEL_WIDTH
from ticker.six.platform.identity import DeviceIdentityStore
from ticker.six.platform.health import HealthCollector
from ticker.six.platform.performance import TickerPiLogger
from ticker.six.platform.update import OtaUpdaterService, UpdateState
from ticker.six.platform.wifi import HotspotDetails, LocalProvisioningService, WiFiRecoveryService, WiFiSetupState
from ticker.six.platform.ble import (
    BLE_CHALLENGE_UUID,
    BLE_CREDENTIALS_UUID,
    BLE_LOCAL_NAME,
    BLE_RESULT_UUID,
    BLE_PAIRING_UUID,
    BLE_SERVICE_UUID,
    BleProvisioningService,
    decrypt_credentials,
    derive_ble_key,
)

__all__ = [
    "AssetCoordinator",
    "AssetFetcher",
    "DeviceIdentityStore",
    "HealthCollector",
    "TickerPiLogger",
    "LongTermAssetCache",
    "HotspotDetails",
    "OtaUpdaterService",
    "PANEL_HEIGHT",
    "PANEL_SIZE",
    "PANEL_WIDTH",
    "PlatformCommands",
    "PersistentAssetStore",
    "SubprocessPlatformCommands",
    "WiFiNetwork",
    "LocalProvisioningService",
    "WiFiRecoveryService",
    "WiFiSetupState",
    "BLE_CHALLENGE_UUID",
    "BLE_CREDENTIALS_UUID",
    "BLE_LOCAL_NAME",
    "BLE_RESULT_UUID",
    "BLE_PAIRING_UUID",
    "BLE_SERVICE_UUID",
    "BleProvisioningService",
    "decrypt_credentials",
    "derive_ble_key",
    "UpdateState",
]
