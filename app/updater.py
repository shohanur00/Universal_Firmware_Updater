
"""
Universal Firmware Updater
Firmware Update Controller

Responsibilities:
- Load and validate firmware
- Establish or reuse a serial connection
- Synchronize with the STM32 bootloader
- Request device ID
- Send firmware size and application address
- Transfer firmware chunks
- Verify firmware CRC
- Report progress, logs and update result

Supports:
1. Standalone usage: updater opens and closes its own port.
2. GUI usage: updater reuses an existing connection and
   leaves the GUI-owned port open after the update.
"""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable

from app.device import DeviceManager
from app.firmware import FirmwareManager
from app.protocol_manager import ProtocolManager
from app.serial_port import SerialPort


# ============================================================
# Update States
# ============================================================

class UpdateState(Enum):
    IDLE = auto()
    LOADING_FIRMWARE = auto()
    CONNECTING = auto()
    SYNCHRONIZING = auto()
    READING_DEVICE_ID = auto()
    SENDING_FIRMWARE_SIZE = auto()
    SETTING_APP_ADDRESS = auto()
    TRANSFERRING_FIRMWARE = auto()
    VERIFYING_FIRMWARE = auto()
    COMPLETED = auto()
    FAILED = auto()


# ============================================================
# Update Result
# ============================================================

@dataclass
class UpdateResult:
    success: bool
    message: str
    firmware_name: str = ""
    firmware_size: int = 0
    firmware_crc: int = 0
    device_id: str = ""


# ============================================================
# Firmware Updater
# ============================================================

class FirmwareUpdater:
    """
    Coordinates the firmware update process.

    Parameters
    ----------
    port:
        Serial port name, e.g. COM7.

    baudrate:
        UART baud rate, e.g. 115200.

    app_start_address:
        Target application's flash start address.

    chunk_size:
        Firmware data bytes per packet. Supported values:
        4, 8 and 16.

    progress_callback:
        Optional callback: callback(percentage, message).

    log_callback:
        Optional callback: callback(message).

    serial_port:
        Optional existing SerialPort instance. When supplied,
        the caller owns the connection lifecycle.

    protocol_manager:
        Optional ProtocolManager using the same SerialPort.
    """

    VALID_CHUNK_SIZES = (4, 8, 16)

    def __init__(
        self,
        port: str,
        baudrate: int,
        app_start_address: int,
        chunk_size: int,
        progress_callback: Callable[[int, str], None] | None = None,
        log_callback: Callable[[str], None] | None = None,
        serial_port: SerialPort | None = None,
        protocol_manager: ProtocolManager | None = None,
    ):
        # ----------------------------------------------------
        # Validate configuration
        # ----------------------------------------------------

        if not port:
            raise ValueError("Serial port must be selected.")

        if baudrate <= 0:
            raise ValueError("Baud rate must be positive.")

        if not 0 <= app_start_address <= 0xFFFFFFFF:
            raise ValueError("Invalid application start address.")

        if chunk_size not in self.VALID_CHUNK_SIZES:
            raise ValueError(
                "Chunk size must be 4, 8, or 16 bytes."
            )

        if protocol_manager is not None and serial_port is None:
            raise ValueError(
                "A ProtocolManager requires its matching "
                "SerialPort to be supplied."
            )

        if (
            protocol_manager is not None
            and protocol_manager.serial_port is not serial_port
        ):
            raise ValueError(
                "ProtocolManager and updater must use the "
                "same SerialPort instance."
            )

        # ----------------------------------------------------
        # Configuration
        # ----------------------------------------------------

        self.port = port
        self.baudrate = baudrate
        self.app_start_address = app_start_address
        self.chunk_size = chunk_size

        self.progress_callback = progress_callback
        self.log_callback = log_callback

        # ----------------------------------------------------
        # Managers
        # ----------------------------------------------------

        self.firmware = FirmwareManager()

        self.device = DeviceManager(
            app_start_address=app_start_address
        )

        # True only when the updater creates the connection.
        # GUI-provided connections remain owned by the GUI.
        self._owns_connection = serial_port is None

        self.serial_port = (
            serial_port
            if serial_port is not None
            else SerialPort(
                port=port,
                baudrate=baudrate,
            )
        )

        self.protocol = (
            protocol_manager
            if protocol_manager is not None
            else ProtocolManager(
                serial_port=self.serial_port
            )
        )

        self.state = UpdateState.IDLE

    # ========================================================
    # Logging
    # ========================================================

    def _log(self, message: str) -> None:
        """Send a message to the supplied logger or stdout."""

        if self.log_callback is not None:
            self.log_callback(message)
        else:
            print(message)

    # ========================================================
    # Progress
    # ========================================================

    def _progress(
        self,
        percentage: int,
        message: str,
    ) -> None:
        """Report clamped progress and a status message."""

        percentage = max(0, min(100, percentage))

        if self.progress_callback is not None:
            self.progress_callback(percentage, message)

        self._log(f"[{percentage:3d}%] {message}")

    # ========================================================
    # Firmware Selection
    # ========================================================

    def select_firmware(
        self,
        file_path: str | Path,
    ) -> None:
        """Load a .bin file and calculate its CRC."""

        self.state = UpdateState.LOADING_FIRMWARE

        try:
            self.firmware.load(file_path)

            self._log(
                f"Firmware: {self.firmware.filename}"
            )
            self._log(
                f"Firmware size: {self.firmware.size} bytes"
            )
            self._log(
                f"Firmware CRC16: 0x{self.firmware.crc:04X}"
            )

            self.state = UpdateState.IDLE

        except Exception:
            self.state = UpdateState.FAILED
            raise

    # ========================================================
    # Update Result Helper
    # ========================================================

    def _make_result(
        self,
        success: bool,
        message: str,
    ) -> UpdateResult:
        """Create a result containing the available firmware/device info."""

        return UpdateResult(
            success=success,
            message=message,
            firmware_name=self.firmware.filename,
            firmware_size=self.firmware.size,
            firmware_crc=self.firmware.crc,
            device_id=self.device.device_id_hex,
        )

    # ========================================================
    # Firmware Update
    # ========================================================

    def run_update(self) -> UpdateResult:
        """
        Execute the firmware update sequence.

        The GUI may supply an already-open serial connection.
        This method closes the port only if this updater owns it.
        """

        if not self.firmware.is_loaded:
            return self._make_result(
                success=False,
                message="Please select a firmware file first.",
            )

        if self.state in (
            UpdateState.CONNECTING,
            UpdateState.SYNCHRONIZING,
            UpdateState.READING_DEVICE_ID,
            UpdateState.SENDING_FIRMWARE_SIZE,
            UpdateState.SETTING_APP_ADDRESS,
            UpdateState.TRANSFERRING_FIRMWARE,
            UpdateState.VERIFYING_FIRMWARE,
        ):
            return self._make_result(
                success=False,
                message="An update is already in progress.",
            )

        try:
            # ------------------------------------------------
            # 1. Ensure serial connection is open
            # ------------------------------------------------

            self.state = UpdateState.CONNECTING

            self._progress(
                0,
                f"Opening {self.port} at {self.baudrate} baud...",
            )

            if not self.serial_port.is_open:
                self.serial_port.open()

            # ------------------------------------------------
            # 2. Synchronize with bootloader
            # ------------------------------------------------

            self.state = UpdateState.SYNCHRONIZING

            self._progress(
                5,
                "Synchronizing with bootloader...",
            )

            # In GUI mode, the connection worker has already
            # received a SYNC ACK. The protocol manager is reused.
            #
            # Do not automatically send a second SYNC here:
            # the bootloader may already be in CONNECTED state.
            # If your bootloader explicitly supports repeated SYNC,
            # a fresh SYNC can instead be added to the protocol flow.

            # ------------------------------------------------
            # 3. Request device ID
            # ------------------------------------------------

            self.state = UpdateState.READING_DEVICE_ID

            self._progress(
                10,
                "Requesting device ID...",
            )

            device_id = self.protocol.request_device_id()

            self.device.set_device_id(device_id)
            self.device.mark_connected()

            self._log(
                f"Device ID: {self.device.device_id_hex}"
            )

            # ------------------------------------------------
            # 4. Send firmware size
            # ------------------------------------------------

            self.state = UpdateState.SENDING_FIRMWARE_SIZE

            self._progress(
                15,
                "Sending firmware size...",
            )

            self.protocol.send_firmware_size(
                self.firmware.size
            )

            # ------------------------------------------------
            # 5. Set application start address
            # ------------------------------------------------

            self.state = UpdateState.SETTING_APP_ADDRESS

            self._progress(
                20,
                (
                    "Setting application address: "
                    f"0x{self.app_start_address:08X}"
                ),
            )

            self.protocol.send_start_address(
                self.app_start_address
            )

            # ------------------------------------------------
            # 6. Transfer firmware chunks
            # ------------------------------------------------

            self.state = UpdateState.TRANSFERRING_FIRMWARE

            total_size = self.firmware.size
            offset = 0

            while offset < total_size:
                chunk = self.firmware.get_chunk(
                    offset=offset,
                    size=self.chunk_size,
                )

                next_offset = offset + len(chunk)
                final_chunk = next_offset == total_size

                self.protocol.send_firmware_chunk(
                    data=chunk,
                    final_chunk=final_chunk,
                )

                offset = next_offset

                percentage = 20 + (
                    offset * 70 // total_size
                )

                self._progress(
                    percentage,
                    f"Transferred {offset}/{total_size} bytes",
                )

            # ------------------------------------------------
            # 7. Verify firmware CRC
            # ------------------------------------------------

            self.state = UpdateState.VERIFYING_FIRMWARE

            self._progress(
                92,
                "Sending firmware CRC...",
            )

            self.protocol.send_firmware_crc(
                self.firmware.crc
            )

            # ------------------------------------------------
            # 8. Success
            # ------------------------------------------------

            self.state = UpdateState.COMPLETED

            self._progress(
                100,
                "Firmware update completed.",
            )

            self._log("Firmware update completed successfully.")

            return self._make_result(
                success=True,
                message="Firmware update completed successfully.",
            )

        except Exception as exc:
            self.state = UpdateState.FAILED

            message = str(exc) or type(exc).__name__

            self._log(f"UPDATE ERROR: {message}")

            return self._make_result(
                success=False,
                message=message,
            )

        finally:
            # Close only connections created by this updater.
            # GUI-owned connections stay open for reconnect/retry.
            if self._owns_connection:
                try:
                    self.serial_port.close()
                except Exception as exc:
                    self._log(
                        f"Warning: failed to close serial port: {exc}"
                    )

            self.device.disconnect()