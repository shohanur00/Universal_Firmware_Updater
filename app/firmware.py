"""
Universal Firmware Updater
Firmware File Manager
"""

from pathlib import Path

from protocol.crc import crc16_ccitt_false


class FirmwareManager:
    """Load and manage a user-selected firmware binary."""

    def __init__(self):
        self.file_path = None
        self.data = b""
        self.crc = 0

    def load(self, file_path: str | Path) -> None:
        """Load a firmware binary selected by the user."""

        if not file_path:
            raise ValueError("Please select a firmware file")

        path = Path(file_path).expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(
                f"Firmware file not found: {path}"
            )

        if path.suffix.lower() != ".bin":
            raise ValueError(
                "Please select a .bin firmware file"
            )

        firmware_data = path.read_bytes()

        if not firmware_data:
            raise ValueError("Firmware file is empty")

        self.file_path = path
        self.data = firmware_data

        # CRC over the original firmware bytes.
        self.crc = crc16_ccitt_false(self.data)

    @property
    def filename(self) -> str:
        return self.file_path.name if self.file_path else ""

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def is_loaded(self) -> bool:
        return bool(self.data)

    def get_chunk(
        self,
        offset: int,
        size: int = 16,
    ) -> bytes:
        """Return the next firmware data chunk."""

        if not self.is_loaded:
            raise RuntimeError("No firmware has been loaded")

        if offset < 0 or offset >= self.size:
            raise ValueError("Firmware offset is out of range")

        if size <= 0:
            raise ValueError(
                "Chunk size must be greater than zero"
            )

        return self.data[offset:offset + size]