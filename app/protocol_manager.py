
"""
Universal Firmware Updater
Protocol Manager

Handles communication between the PC updater
and the STM32 bootloader.
"""

import struct
import time

from app.serial_port import SerialPort

from protocol.commands import (
    CMD_SYNC,
    CMD_DEVICE_ID_REQ,
    CMD_DEVICE_ID_RES,
    CMD_DEVICE_ID_CONFIRM,
    CMD_FW_SIZE,
    CMD_SET_APP_START_ADDRESS,
    CMD_FW_DATA,
    CMD_CRC_CHECK,
    CMD_ACK,
    CMD_NACK,
    CMD_UPDATE_SUCCESSFUL,
    CMD_ERASE_FIRMWARE,
    ERROR_NONE,
    DEVICE_ID_SIZE,
    MAX_DATA_LENGTH,
    PACKET_TYPE_COMMAND,
    SOF,
    MAX_FRAME_LENGTH,
)

from protocol.frame import (
    create_command,
    create_command_data,
    create_firmware_data,
    decode_frame,
)


class ProtocolError(Exception):
    """Raised when bootloader communication fails."""


class ProtocolManager:
    """Manage the STM32 bootloader protocol."""

    def __init__(
        self,
        serial_port: SerialPort,
        response_timeout: float = 5.0,
        expected_device_id: bytes | None = None,
    ):
        self.serial_port = serial_port
        self.response_timeout = response_timeout

        # Optional exact UID for device identity verification.
        self.expected_device_id = expected_device_id

        # Connection verification state.
        self._device_id: bytes | None = None
        self._device_verified = False

    # ========================================================================
    # Receive Frame
    # ========================================================================

    def receive_frame(self, timeout: float | None = None):
        """Receive and validate one complete frame."""

        if timeout is None:
            timeout = self.response_timeout

        deadline = time.monotonic() + timeout
        buffer = bytearray()

        while time.monotonic() < deadline:
            available = self.serial_port.bytes_available

            if available:
                buffer.extend(self.serial_port.read_available())

            # Find SOF and discard preceding noise.
            while buffer and buffer[0] != SOF:
                del buffer[0]

            if len(buffer) < 2:
                time.sleep(0.001)
                continue

            length = buffer[1]

            # SOF + LENGTH + TYPE/COMMAND/DATA + CRC16
            total_length = 1 + 1 + length + 2

            if total_length < 6 or total_length > MAX_FRAME_LENGTH:
                del buffer[0]
                continue

            if len(buffer) < total_length:
                time.sleep(0.001)
                continue

            raw_frame = bytes(buffer[:total_length])
            del buffer[:total_length]

            try:
                return decode_frame(raw_frame)
            except ValueError:
                # Ignore malformed frames.
                continue

        raise TimeoutError(
            "Timed out waiting for a valid bootloader frame"
        )

    # ========================================================================
    # ACK / NACK
    # ========================================================================

    @staticmethod
    def _raise_for_nack(frame) -> None:
        """Raise ProtocolError if the frame is a NACK."""

        if frame.command != CMD_NACK:
            return

        error_code = (
            frame.data[0]
            if frame.data
            else ERROR_NONE
        )

        raise ProtocolError(
            f"Bootloader returned NACK: "
            f"error code 0x{error_code:02X}"
        )

    def wait_for_ack(self, timeout: float | None = None) -> None:
        """Wait for ACK and raise an error on NACK."""

        deadline = time.monotonic() + (
            self.response_timeout if timeout is None else timeout
        )

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()

            frame = self.receive_frame(
                timeout=max(remaining, 0.001)
            )

            if frame.command == CMD_ACK:
                return

            self._raise_for_nack(frame)

        raise TimeoutError("Timed out waiting for ACK")

    def wait_for_command(
        self,
        expected_command: int,
        timeout: float | None = None,
    ):
        """Wait for a specific command response."""

        deadline = time.monotonic() + (
            self.response_timeout if timeout is None else timeout
        )

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()

            frame = self.receive_frame(
                timeout=max(remaining, 0.001)
            )

            if frame.command == expected_command:
                return frame

            self._raise_for_nack(frame)

        raise TimeoutError(
            f"Expected command 0x{expected_command:02X} "
            f"not received"
        )

    # ========================================================================
    # SYNC
    # ========================================================================

    def send_sync(self) -> None:
        """
        Send SYNC and wait for ACK.

        SYNC alone does not establish a verified connection.
        """

        if not self.serial_port.is_open:
            raise ProtocolError("Serial port is not open.")

        self._device_id = None
        self._device_verified = False

        self.serial_port.clear_rx()

        self.serial_port.write(
            create_command(CMD_SYNC)
        )

        self.wait_for_ack(timeout=7.0)

    # ========================================================================
    # Device ID
    # ========================================================================

    def request_device_id(self) -> bytes:
        """
        Request the MCU UID.

        If this manager has already verified the device during
        the current connection, return the cached UID instead of
        sending a second request.
        """

        if not self.serial_port.is_open:
            raise ProtocolError("Serial port is not open.")

        if self._device_verified and self._device_id is not None:
            return self._device_id

        self.serial_port.write(
            create_command(CMD_DEVICE_ID_REQ)
        )

        frame = self.wait_for_command(
            CMD_DEVICE_ID_RES
        )

        if frame.frame_type != PACKET_TYPE_COMMAND:
            raise ProtocolError(
                "Unexpected packet type in device ID response"
            )

        if len(frame.data) != DEVICE_ID_SIZE:
            raise ProtocolError(
                f"Invalid device ID size: "
                f"{len(frame.data)} bytes"
            )

        device_id = bytes(frame.data)

        # Reject obviously invalid UID values.
        if not any(device_id):
            raise ProtocolError("Device ID contains only zeros.")

        if all(value == 0xFF for value in device_id):
            raise ProtocolError("Device ID contains only 0xFF.")

        return device_id

    def verify_device_id(self, device_id: bytes) -> bool:
        """
        Validate UID format and, if configured, compare it
        with the expected MCU UID.
        """

        if len(device_id) != DEVICE_ID_SIZE:
            return False

        if not any(device_id):
            return False

        if all(value == 0xFF for value in device_id):
            return False

        if self.expected_device_id is not None:
            return device_id == self.expected_device_id

        # No expected UID configured: format validation only.
        return True

    def send_device_id_confirm(self) -> None:
        """
        Confirm the device only after successful UID verification.
        """

        if self._device_id is None:
            raise ProtocolError(
                "Device ID has not been received."
            )

        if not self.verify_device_id(self._device_id):
            raise ProtocolError(
                "Device ID verification failed."
            )

        self.serial_port.write(
            create_command(CMD_DEVICE_ID_CONFIRM)
        )

        self.wait_for_ack(timeout=self.response_timeout)

        # Mark verified only after the MCU confirms.
        self._device_verified = True

    def connect_and_verify(self) -> bytes:
        """
        Complete the full handshake:

        SYNC -> ACK -> DEVICE_ID_REQ -> DEVICE_ID_RES
        -> UID verification -> DEVICE_ID_CONFIRM -> ACK
        """

        self.send_sync()

        device_id = self.request_device_id()

        if not self.verify_device_id(device_id):
            self._device_id = None
            self._device_verified = False

            raise ProtocolError(
                "Device ID verification failed. "
                "Connection was not verified."
            )

        self._device_id = device_id

        self.send_device_id_confirm()

        return device_id

    @property
    def is_device_verified(self) -> bool:
        """Return whether the MCU handshake was verified."""

        return self._device_verified

    # ========================================================================
    # Firmware Size
    # ========================================================================

    def send_firmware_size(self, firmware_size: int) -> None:
        """Send firmware size as a little-endian uint32."""

        if not 0 < firmware_size <= 0xFFFFFFFF:
            raise ValueError("Invalid firmware size")

        data = struct.pack("<I", firmware_size)

        self.serial_port.write(
            create_command_data(CMD_FW_SIZE, data)
        )

        self.wait_for_ack()

    # ========================================================================
    # Application Start Address
    # ========================================================================

    def send_start_address(self, address: int) -> None:
        """Send application start address as a little-endian uint32."""

        if not 0 <= address <= 0xFFFFFFFF:
            raise ValueError(
                "Invalid application start address"
            )

        data = struct.pack("<I", address)

        self.serial_port.write(
            create_command_data(
                CMD_SET_APP_START_ADDRESS,
                data,
            )
        )

        self.wait_for_ack(timeout=10.0)

    # ========================================================================
    # Firmware Data
    # ========================================================================

    def send_firmware_chunk(
        self,
        data: bytes,
        final_chunk: bool = False,
    ) -> None:
        """Send firmware data and validate the response."""

        if not data or len(data) > MAX_DATA_LENGTH:
            raise ValueError(
                f"Firmware chunk must contain 1 to "
                f"{MAX_DATA_LENGTH} bytes"
            )

        self.serial_port.write(
            create_firmware_data(data)
        )

        expected_response = (
            CMD_UPDATE_SUCCESSFUL
            if final_chunk
            else CMD_ACK
        )

        self.wait_for_command(expected_response)

    # ========================================================================
    # Firmware CRC
    # ========================================================================

    def send_firmware_crc(self, firmware_crc: int) -> None:
        """Send firmware CRC as a big-endian uint16."""

        if not 0 <= firmware_crc <= 0xFFFF:
            raise ValueError(
                "Firmware CRC must be a uint16"
            )

        data = struct.pack(">H", firmware_crc)

        self.serial_port.write(
            create_command_data(
                CMD_CRC_CHECK,
                data,
            )
        )

        self.wait_for_ack()

    # ========================================================================
    # Erase Firmware
    # ========================================================================

    def erase_firmware(self) -> None:
        """Request application firmware erase and wait for ACK."""

        if not self.serial_port.is_open:
            raise ProtocolError("Serial port is not open.")

        if not self._device_verified:
            raise ProtocolError(
                "Connect and verify the device before erasing."
            )

        self.serial_port.clear_rx()

        packet = create_command_data(
            CMD_ERASE_FIRMWARE,
            b"",
        )

        self.serial_port.write(packet)

        self.wait_for_ack(timeout=15.0)

        # The old application has been erased.
        self._device_id = None
        self._device_verified = False