"""
Universal Firmware Updater
Protocol Command Definitions

STM32 Bootloader Communication Protocol
"""


# ============================================================================
# Protocol Configuration
# ============================================================================

SOF = 0xA5

PACKET_TYPE_COMMAND = 0x01
PACKET_TYPE_DATA = 0x02

MAX_DATA_LENGTH = 16
MAX_FRAME_LENGTH = 22


# ============================================================================
# Command Definitions
# ============================================================================

CMD_NONE = 0x00

CMD_SYNC = 0x20

CMD_FW_UPDATE_REQ = 0x31
CMD_FW_UPDATE_RES = 0x37

CMD_DEVICE_ID_REQ = 0x3C
CMD_DEVICE_ID_RES = 0x3F

CMD_FW_SIZE = 0x42
CMD_FW_OVER_SIZE = 0x45

CMD_READY = 0x48

CMD_SET_APP_START_ADDRESS = 0x4A
CMD_APP_START_ADDRESS_ERROR = 0x4B

CMD_FW_DATA = 0x50

CMD_CRC_CHECK = 0x3B

CMD_UPDATE_SUCCESSFUL = 0x54

CMD_ACK = 0x15
CMD_NACK = 0x59
CMD_RETX = 0x19


# ============================================================================
# Error Codes
# ============================================================================

ERROR_NONE = 0x00
ERROR_CRC = 0x01
ERROR_LENGTH = 0x02
ERROR_COMMAND = 0x03
ERROR_STATE = 0x04
ERROR_ADDRESS = 0x05
ERROR_SIZE = 0x06
ERROR_PROTOCOL = 0x07
ERROR_DEVICE_ID = 0x08
ERROR_NO_RETRY_PACKET = 0x09
ERROR_FLASH_ERASE = 0x0A
ERROR_DATA = 0x0B
CMD_ERASE_FIRMWARE = 0x60
# Device Identification
CMD_DEVICE_ID_REQ     = 0x3C
CMD_DEVICE_ID_CONFIRM = 0x3D
CMD_DEVICE_ID_RES     = 0x3F


# ============================================================================
# Protocol Limits
# ============================================================================

DEVICE_ID_SIZE = 12

MAX_RETRY_COUNT = 10


# ============================================================================
# Bootloader States
# ============================================================================

STATE_WAIT_SYNC = "WAIT_SYNC"

STATE_CONNECTED = "CONNECTED"

STATE_WAIT_FW_LENGTH = "WAIT_FW_LENGTH"

STATE_WAIT_FW_START_ADDRESS = "WAIT_FW_START_ADDRESS"

STATE_READY = "READY"

STATE_RECEIVING = "RECEIVING"

STATE_COMPLETE = "COMPLETE"

STATE_PROGRAMMING = "PROGRAMMING"

STATE_VALID = "VALID"