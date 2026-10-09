"""
Universal Firmware Updater
Device Information Manager
"""


from dataclasses import dataclass


# ============================================================================
# Device Configuration
# ============================================================================

DEFAULT_APP_START_ADDRESS = 0x08004000
DEVICE_ID_SIZE = 12


# ============================================================================
# Device Information
# ============================================================================

@dataclass
class DeviceInfo:
    """Information received from the connected device."""

    device_id: bytes = b""
    app_start_address: int = DEFAULT_APP_START_ADDRESS
    connected: bool = False

    @property
    def device_id_hex(self) -> str:
        """Return device ID as a hexadecimal string."""

        if not self.device_id:
            return "Unknown"

        return self.device_id.hex(" ").upper()


# ============================================================================
# Device Manager
# ============================================================================

class DeviceManager:
    """Store and manage connected device information."""

    def __init__(
        self,
        app_start_address: int = DEFAULT_APP_START_ADDRESS,
    ):
        self.info = DeviceInfo(
            app_start_address=app_start_address,
        )

    # ========================================================================
    # Connection
    # ========================================================================

    def mark_connected(self) -> None:
        """Mark the device as connected."""

        self.info.connected = True

    def disconnect(self) -> None:
        """Clear connection and device identification state."""

        self.info.connected = False
        self.info.device_id = b""

    @property
    def is_connected(self) -> bool:
        return self.info.connected

    # ========================================================================
    # Device ID
    # ========================================================================

    def set_device_id(self, device_id: bytes) -> None:
        """Store the device ID received from the bootloader."""

        if not isinstance(device_id, bytes):
            raise TypeError("device_id must be bytes")

        if len(device_id) != DEVICE_ID_SIZE:
            raise ValueError(
                f"Device ID must be exactly {DEVICE_ID_SIZE} bytes"
            )

        self.info.device_id = device_id

    @property
    def device_id(self) -> bytes:
        return self.info.device_id

    @property
    def device_id_hex(self) -> str:
        return self.info.device_id_hex

    # ========================================================================
    # Application Address
    # ========================================================================

    def set_app_start_address(self, address: int) -> None:
        """Set the application start address."""

        if not isinstance(address, int):
            raise TypeError("Address must be an integer")

        if not 0 <= address <= 0xFFFFFFFF:
            raise ValueError("Address is outside the uint32 range")

        self.info.app_start_address = address

    @property
    def app_start_address(self) -> int:
        return self.info.app_start_address