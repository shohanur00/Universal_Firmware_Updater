"""
Universal Firmware Updater
Serial Port Driver

Responsibilities:
- Open and close the serial port
- Transmit and receive bytes
- Read available data
- Clear the RX buffer
- Provide connection status
"""

import time

import serial
from serial import SerialException


class SerialPort:
    """Simple wrapper around pyserial.Serial."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 0.1,
        write_timeout: float = 2.0,
    ):
        if not port:
            raise ValueError("Serial port must be selected.")

        if baudrate <= 0:
            raise ValueError("Baud rate must be positive.")

        if timeout < 0:
            raise ValueError("Timeout cannot be negative.")

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout

        self._serial = None

    @property
    def is_open(self) -> bool:
        """Return True if the serial port is open."""
        return (
            self._serial is not None
            and self._serial.is_open
        )

    def open(self) -> None:
        """Open the serial port."""
        if self.is_open:
            return

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=self.write_timeout,
            )

            # Discard stale bytes from a previous session.
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

        except (SerialException, OSError) as exc:
            self._serial = None
            raise ConnectionError(
                f"Failed to open {self.port}: {exc}"
            ) from exc

    def close(self) -> None:
        """Close the serial port safely."""
        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            finally:
                self._serial = None

    def write(self, data: bytes) -> int:
        """Transmit bytes and return the number of bytes written."""
        self._require_open()

        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("Serial write data must be bytes-like.")

        try:
            return self._serial.write(bytes(data))
        except (SerialException, OSError) as exc:
            raise ConnectionError(
                f"Serial write failed on {self.port}: {exc}"
            ) from exc

    def read(self, size: int = 1) -> bytes:
        """Read up to size bytes, using the configured timeout."""
        self._require_open()

        if size < 0:
            raise ValueError("Read size cannot be negative.")

        try:
            return self._serial.read(size)
        except (SerialException, OSError) as exc:
            raise ConnectionError(
                f"Serial read failed on {self.port}: {exc}"
            ) from exc

    def read_available(self) -> bytes:
        """Read all bytes currently available in the RX buffer."""
        self._require_open()

        try:
            available = self._serial.in_waiting

            if available <= 0:
                return b""

            return self._serial.read(available)

        except (SerialException, OSError) as exc:
            raise ConnectionError(
                f"Serial receive failed on {self.port}: {exc}"
            ) from exc

    @property
    def bytes_available(self) -> int:
        """Return the number of bytes waiting in the RX buffer."""
        self._require_open()
        return self._serial.in_waiting

    def clear_rx(self) -> None:
        """Clear the receive buffer."""
        self._require_open()
        self._serial.reset_input_buffer()

    def clear_tx(self) -> None:
        """Clear the transmit buffer."""
        self._require_open()
        self._serial.reset_output_buffer()

    def reset_input_buffer(self) -> None:
        """Compatibility alias for clearing RX."""
        self.clear_rx()

    def reset_output_buffer(self) -> None:
        """Compatibility alias for clearing TX."""
        self.clear_tx()

    def wait_for_transmission(self) -> None:
        """Wait until pending serial output has been transmitted."""
        self._require_open()
        self._serial.flush()

    def _require_open(self) -> None:
        """Raise an error if the port is not open."""
        if not self.is_open:
            raise ConnectionError(
                f"Serial port {self.port} is not open."
            )

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

