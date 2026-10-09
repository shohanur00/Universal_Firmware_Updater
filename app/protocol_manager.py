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
    CMD_FW_SIZE,
    CMD_SET_APP_START_ADDRESS,
    CMD_FW_DATA,
    CMD_CRC_CHECK,
    CMD_ACK,
    CMD_NACK,
    CMD_UPDATE_SUCCESSFUL,
    ERROR_NONE,
    DEVICE_ID_SIZE,
    MAX_DATA_LENGTH,
    PACKET_TYPE_COMMAND,
    PACKET_TYPE_DATA,
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
    ):
        self.serial_port = serial_port
        self.response_timeout = response_timeout

    # ========================================================================
    # Receive Frame
    # ========================================================================

    def receive_frame(self, timeout: float | None = None):
        """
        Receive and validate one complete frame.

        CRC and frame structure are checked by decode_frame().
        """

        if timeout is None:
            timeout = self.response_timeout

        deadline = time.monotonic() + timeout
        buffer = bytearray()

        while time.monotonic() < deadline:
            available = self.serial_port.bytes_available

            if available:
                buffer.extend(
                    self.serial_port.read_available()
                )

            # Find SOF and discard preceding noise.
            while buffer and buffer[0] != SOF:
                del buffer[0]

            if len(buffer) < 2:
                time.sleep(0.001)
                continue

            length = buffer[1]

            # LENGTH includes TYPE + COMMAND + DATA.
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
                # Ignore malformed frame and continue listening.
                continue

        raise TimeoutError(
            "Timed out waiting for a valid bootloader frame"
        )

    # ========================================================================
    # Wait For Command
    # ========================================================================

    def wait_for_command(
        self,
        expected_command: int,
        timeout: float | None = None,
    ):
        """Wait until a frame with the expected command arrives."""

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

        raise TimeoutError(
            f"Expected command 0x{expected_command:02X} not received"
        )

    # ========================================================================
    # ACK / NACK
    # ========================================================================

    def wait_for_ack(self, timeout: float | None = None) -> None:
        """Wait for ACK and raise an error if NACK is received."""

        deadline = time.monotonic() + (
            self.response_timeout if timeout is None else timeout
        )

        while time.monotonic() < deadline:
            frame = self.receive_frame(
                timeout=max(deadline - time.monotonic(), 0.001)
            )

            if frame.command == CMD_ACK:
                return

            if frame.command == CMD_NACK:
                error_code = (
                    frame.data[0]
                    if frame.data
                    else ERROR_NONE
                )

                raise ProtocolError(
                    f"Bootloader returned NACK: "
                    f"error code 0x{error_code:02X}"
                )

        raise TimeoutError("Timed out waiting for ACK")

    # ========================================================================
    # SYNC
    # ========================================================================

    def send_sync(self) -> None:
        """Send SYNC and wait for ACK."""

        self.serial_port.clear_rx()
        self.serial_port.write(
            create_command(CMD_SYNC)
        )

        self.wait_for_ack(timeout=7.0)

    # ========================================================================
    # Device ID
    # ========================================================================

    def request_device_id(self) -> bytes:
        """Request the STM32 device ID."""

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
                f"Invalid device ID size: {len(frame.data)} bytes"
            )

        return frame.data

    # ========================================================================
    # Firmware Size
    # ========================================================================

    def send_firmware_size(self, firmware_size: int) -> None:
        """Send firmware size as a little-endian uint32."""

        if not 0 < firmware_size <= 0xFFFFFFFF:
            raise ValueError("Invalid firmware size")

        data = struct.pack("<I", firmware_size)

        self.serial_port.write(
            create_command_data(
                CMD_FW_SIZE,
                data,
            )
        )

        self.wait_for_ack()

    # ========================================================================
    # Application Start Address
    # ========================================================================

    def send_start_address(self, address: int) -> None:
        """Send application start address as a little-endian uint32."""

        if not 0 <= address <= 0xFFFFFFFF:
            raise ValueError("Invalid application start address")

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
        """Send one firmware data packet and validate its response."""

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

        frame = self.wait_for_command(
            expected_response
        )

        if frame.command == CMD_UPDATE_SUCCESSFUL:
            return

        if frame.command == CMD_ACK:
            return

    # ========================================================================
    # Firmware CRC
    # ========================================================================

    def send_firmware_crc(self, firmware_crc: int) -> None:
        """Send firmware CRC as a big-endian uint16."""

        if not 0 <= firmware_crc <= 0xFFFF:
            raise ValueError("Firmware CRC must be a uint16")

        data = struct.pack(">H", firmware_crc)

        self.serial_port.write(
            create_command_data(
                CMD_CRC_CHECK,
                data,
            )
        )

        self.wait_for_ack()