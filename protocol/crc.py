"""
CRC16-CCITT-FALSE implementation.

Protocol:
    Polynomial : 0x1021
    Initial    : 0xFFFF
    RefIn      : False
    RefOut     : False
    XOROut     : 0x0000
"""


CRC16_CCITT_FALSE_POLY = 0x1021
CRC16_CCITT_FALSE_INIT = 0xFFFF


def crc16_ccitt_false(data: bytes) -> int:
    """
    Calculate CRC16-CCITT-FALSE.

    Args:
        data: Input data as bytes.

    Returns:
        16-bit CRC value.
    """

    crc = CRC16_CCITT_FALSE_INIT

    for byte in data:
        crc ^= byte << 8

        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ CRC16_CCITT_FALSE_POLY
            else:
                crc <<= 1

            crc &= 0xFFFF

    return crc


def crc16_to_bytes(crc: int) -> bytes:
    """
    Convert CRC16 value to two bytes.

    CRC byte order:
        MSB first
        [CRC_HIGH, CRC_LOW]
    """

    return crc.to_bytes(2, byteorder="big")


def crc16_from_bytes(data: bytes) -> int:
    """
    Convert two CRC bytes into an integer.

    Args:
        data: Exactly 2 bytes.

    Returns:
        16-bit CRC value.
    """

    if len(data) != 2:
        raise ValueError("CRC must contain exactly 2 bytes")

    return int.from_bytes(data, byteorder="big")