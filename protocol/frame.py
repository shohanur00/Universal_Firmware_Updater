"""
Universal Firmware Updater
Protocol Frame Encoder / Decoder

STM32 Bootloader Communication Protocol

Frame Format:

    SOF | LENGTH | TYPE | COMMAND | DATA | CRC_H | CRC_L

CRC is calculated over:

    LENGTH + TYPE + COMMAND + DATA

SOF is NOT included in CRC calculation.

CRC:
    CRC16-CCITT-FALSE
    Polynomial : 0x1021
    Initial    : 0xFFFF
    RefIn      : False
    RefOut     : False
    XOROut     : 0x0000
    Byte Order : Big Endian
"""


from dataclasses import dataclass


from protocol.commands import (
    SOF,
    PACKET_TYPE_COMMAND,
    PACKET_TYPE_DATA,
    MAX_DATA_LENGTH,
    MAX_FRAME_LENGTH,
    CMD_FW_DATA,
)


from protocol.crc import (
    crc16_ccitt_false,
    crc16_to_bytes,
)


# ============================================================================
# Frame Data Structure
# ============================================================================

@dataclass
class Frame:
    """
    Decoded protocol frame.
    """

    frame_type: int
    command: int
    data: bytes
    crc: int


# ============================================================================
# Frame Encoder
# ============================================================================

def encode_frame(
    frame_type: int,
    command: int,
    data: bytes = b"",
) -> bytes:
    """
    Create a complete protocol frame.

    Frame:

        SOF | LENGTH | TYPE | COMMAND | DATA | CRC_H | CRC_L

    LENGTH:

        TYPE + COMMAND + DATA

    CRC input:

        LENGTH + TYPE + COMMAND + DATA

    SOF is NOT included in CRC calculation.
    """

    # ------------------------------------------------------------------------
    # Validate data type
    # ------------------------------------------------------------------------

    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")

    # ------------------------------------------------------------------------
    # Validate data length
    # ------------------------------------------------------------------------

    if len(data) > MAX_DATA_LENGTH:
        raise ValueError(
            f"Data exceeds maximum size of "
            f"{MAX_DATA_LENGTH} bytes"
        )

    # ------------------------------------------------------------------------
    # Calculate LENGTH
    #
    # LENGTH = TYPE + COMMAND + DATA
    # ------------------------------------------------------------------------

    length = 2 + len(data)

    # ------------------------------------------------------------------------
    # Create frame body
    #
    # BODY = LENGTH + TYPE + COMMAND + DATA
    # ------------------------------------------------------------------------

    body = bytes([
        length,
        frame_type,
        command,
    ]) + data

    # ------------------------------------------------------------------------
    # Calculate CRC
    #
    # IMPORTANT:
    # SOF is NOT included.
    # ------------------------------------------------------------------------

    crc = crc16_ccitt_false(body)

    # ------------------------------------------------------------------------
    # Create complete frame
    # ------------------------------------------------------------------------

    frame = (
        bytes([SOF])
        + body
        + crc16_to_bytes(crc)
    )

    # ------------------------------------------------------------------------
    # Validate total frame length
    # ------------------------------------------------------------------------

    if len(frame) > MAX_FRAME_LENGTH:
        raise ValueError(
            "Frame exceeds maximum frame length"
        )

    return frame


# ============================================================================
# Command Frame
# ============================================================================

def create_command(command: int) -> bytes:
    """
    Create a command-only frame.

    Example:

        SYNC

        A5 02 01 20 CRC_H CRC_L
    """

    return encode_frame(
        frame_type=PACKET_TYPE_COMMAND,
        command=command,
        data=b"",
    )


# ============================================================================
# Command + Data Frame
# ============================================================================

def create_command_data(
    command: int,
    data: bytes,
) -> bytes:
    """
    Create a command frame containing data.

    Example:

        A5 LENGTH 01 COMMAND DATA CRC_H CRC_L
    """

    return encode_frame(
        frame_type=PACKET_TYPE_COMMAND,
        command=command,
        data=data,
    )


# ============================================================================
# Firmware Data Frame
# ============================================================================

def create_firmware_data(
    data: bytes,
) -> bytes:
    """
    Create firmware data frame.

    TYPE:

        PACKET_TYPE_DATA

    COMMAND:

        CMD_FW_DATA
    """

    return encode_frame(
        frame_type=PACKET_TYPE_DATA,
        command=CMD_FW_DATA,
        data=data,
    )


# ============================================================================
# Frame Decoder
# ============================================================================

def decode_frame(frame: bytes) -> Frame:
    """
    Decode and validate a complete received frame.

    Raises:
        ValueError:
            If the frame is invalid.
    """

    # ------------------------------------------------------------------------
    # Minimum valid frame:
    #
    # SOF + LENGTH + TYPE + COMMAND + CRC_H + CRC_L
    #
    # = 6 bytes
    # ------------------------------------------------------------------------

    if len(frame) < 6:
        raise ValueError(
            "Frame is too short"
        )

    # ------------------------------------------------------------------------
    # Check SOF
    # ------------------------------------------------------------------------

    if frame[0] != SOF:
        raise ValueError(
            "Invalid SOF"
        )

    # ------------------------------------------------------------------------
    # Read LENGTH
    # ------------------------------------------------------------------------

    length = frame[1]

    # ------------------------------------------------------------------------
    # Calculate expected complete frame length
    #
    # SOF     = 1
    # LENGTH  = 1
    # BODY    = length
    # CRC     = 2
    #
    # TOTAL   = 1 + 1 + length + 2
    # ------------------------------------------------------------------------

    expected_length = (
        1 + 1 + length + 2
    )

    if len(frame) != expected_length:
        raise ValueError(
            "Invalid frame length"
        )

    # ------------------------------------------------------------------------
    # Maximum frame size
    # ------------------------------------------------------------------------

    if len(frame) > MAX_FRAME_LENGTH:
        raise ValueError(
            "Frame exceeds maximum length"
        )

    # ------------------------------------------------------------------------
    # Extract received CRC
    # ------------------------------------------------------------------------

    received_crc = int.from_bytes(
        frame[-2:],
        byteorder="big",
    )

    # ------------------------------------------------------------------------
    # Calculate CRC
    #
    # CRC input:
    #
    # LENGTH + TYPE + COMMAND + DATA
    #
    # SOF excluded
    # CRC bytes excluded
    # ------------------------------------------------------------------------

    calculated_crc = crc16_ccitt_false(
        frame[1:-2]
    )

    # ------------------------------------------------------------------------
    # CRC validation
    # ------------------------------------------------------------------------

    if received_crc != calculated_crc:
        raise ValueError(
            f"CRC mismatch: "
            f"received=0x{received_crc:04X}, "
            f"calculated=0x{calculated_crc:04X}"
        )

    # ------------------------------------------------------------------------
    # Extract TYPE
    # ------------------------------------------------------------------------

    frame_type = frame[2]

    # ------------------------------------------------------------------------
    # Extract COMMAND
    # ------------------------------------------------------------------------

    command = frame[3]

    # ------------------------------------------------------------------------
    # Calculate DATA length
    #
    # LENGTH = TYPE + COMMAND + DATA
    #
    # DATA = LENGTH - 2
    # ------------------------------------------------------------------------

    data_length = length - 2

    if data_length < 0:
        raise ValueError(
            "Invalid LENGTH field"
        )

    # ------------------------------------------------------------------------
    # Extract DATA
    # ------------------------------------------------------------------------

    data = frame[
        4:4 + data_length
    ]

    # ------------------------------------------------------------------------
    # Return decoded frame
    # ------------------------------------------------------------------------

    return Frame(
        frame_type=frame_type,
        command=command,
        data=data,
        crc=received_crc,
    )