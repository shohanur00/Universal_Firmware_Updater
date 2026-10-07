import serial
import struct
import time
import sys


# ============================================================
# Configuration
# ============================================================

PORT = "COM6"                 # <-- Change this
BAUDRATE = 115200

SOF = 0xA5

MAX_DATA_SIZE = 16

# Bootloader commands
CMD_SYNC                  = 0x20
CMD_FW_UPDATE_REQ         = 0x31
CMD_FW_UPDATE_RES         = 0x37
CMD_DEVICE_ID_REQ         = 0x3C
CMD_DEVICE_ID_RES         = 0x3F
CMD_FW_SIZE               = 0x42
CMD_FW_OVER_SIZE          = 0x45
CMD_SET_APP_START_ADDRESS = 0x4A
CMD_APP_START_ADDRESS_ERR = 0x4B
CMD_FW_DATA               = 0x50
CMD_READY_FOR_DATA        = 0x48
CMD_UPDATE_SUCCESSFUL     = 0x54
CMD_ACK                   = 0x15
CMD_NACK                  = 0x59
CMD_RETX                  = 0x19
CMD_CRC_CHECK             = 0x3B

# Error codes
ERROR_NONE            = 0x00
ERROR_CRC             = 0x01
ERROR_LENGTH          = 0x02
ERROR_COMMAND         = 0x03
ERROR_STATE            = 0x04
ERROR_ADDRESS          = 0x05
ERROR_SIZE             = 0x06
ERROR_PROTOCOL         = 0x07

ERROR_DEVICE_ID        = 0x08
ERROR_NO_RETRY_PACKET  = 0x09
ERROR_FLASH_ERASE      = 0x0A
ERROR_DATA             = 0x0B

# STM32G4 application address
APP_START_ADDRESS = 0x08004000

# Firmware file
FIRMWARE_FILE = "firmware.bin"


# ============================================================
# CRC16-CCITT-FALSE
# ============================================================

def crc16_ccitt_false(data):
    crc = 0xFFFF

    for byte in data:
        crc ^= (byte << 8)

        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


# ============================================================
# Packet Builder
# ============================================================

def make_packet(command, data=b""):
    payload = bytes([command]) + data

    length = len(payload)

    if length > MAX_DATA_SIZE:
        raise ValueError(
            f"Payload too large: {length} bytes"
        )

    # SOF + LENGTH + DATA
    frame_without_crc = (
        bytes([SOF]) +
        bytes([length]) +
        payload
    )

    crc = crc16_ccitt_false(frame_without_crc)

    # CRC = little endian
    frame = (
        frame_without_crc +
        struct.pack("<H", crc)
    )

    return frame


# ============================================================
# Packet Receiver
# ============================================================

def receive_packet(ser, timeout=2.0):

    start_time = time.time()

    # -------------------------
    # Wait for SOF
    # -------------------------

    while True:

        if time.time() - start_time > timeout:
            raise TimeoutError("Timeout waiting for SOF")

        byte = ser.read(1)

        if not byte:
            continue

        if byte[0] == SOF:
            break

    # -------------------------
    # Read LENGTH
    # -------------------------

    length_byte = ser.read(1)

    if len(length_byte) != 1:
        raise TimeoutError("Timeout waiting for LENGTH")

    length = length_byte[0]

    if length == 0 or length > MAX_DATA_SIZE:
        raise ValueError(
            f"Invalid packet length: {length}"
        )

    # -------------------------
    # Read DATA
    # -------------------------

    data = ser.read(length)

    if len(data) != length:
        raise TimeoutError("Timeout waiting for DATA")

    # -------------------------
    # Read CRC
    # -------------------------

    crc_bytes = ser.read(2)

    if len(crc_bytes) != 2:
        raise TimeoutError("Timeout waiting for CRC")

    received_crc = struct.unpack("<H", crc_bytes)[0]

    # -------------------------
    # Verify CRC
    # -------------------------

    frame_without_crc = (
        bytes([SOF]) +
        bytes([length]) +
        data
    )

    calculated_crc = crc16_ccitt_false(
        frame_without_crc
    )

    if received_crc != calculated_crc:

        print(
            f"[RX] CRC ERROR "
            f"received=0x{received_crc:04X} "
            f"calculated=0x{calculated_crc:04X}"
        )

        return None

    command = data[0]
    payload = data[1:]

    return command, payload


# ============================================================
# Send Packet
# ============================================================

def send_packet(ser, command, data=b""):

    packet = make_packet(command, data)

    print(
        f"[TX] CMD=0x{command:02X} "
        f"DATA={len(data)} "
        f"FRAME={packet.hex(' ')}"
    )

    ser.write(packet)
    ser.flush()


# ============================================================
# Wait for ACK
# ============================================================

def wait_for_ack(ser):

    response = receive_packet(ser)

    if response is None:
        raise RuntimeError("Bootloader response CRC error")

    command, data = response

    print(
        f"[RX] CMD=0x{command:02X} "
        f"DATA={data.hex(' ')}"
    )

    if command == CMD_ACK:
        return True

    if command == CMD_NACK:

        error = data[0] if len(data) > 0 else 0xFF

        raise RuntimeError(
            f"Bootloader NACK, error=0x{error:02X}"
        )

    raise RuntimeError(
        f"Unexpected response: 0x{command:02X}"
    )


# ============================================================
# Wait for specific command
# ============================================================

def wait_for_command(ser, expected_command):

    response = receive_packet(ser)

    if response is None:
        raise RuntimeError("Bootloader response CRC error")

    command, data = response

    print(
        f"[RX] CMD=0x{command:02X} "
        f"DATA={data.hex(' ')}"
    )

    if command == CMD_NACK:

        error = data[0] if len(data) > 0 else 0xFF

        raise RuntimeError(
            f"Bootloader NACK, error=0x{error:02X}"
        )

    if command != expected_command:

        raise RuntimeError(
            f"Expected 0x{expected_command:02X}, "
            f"received 0x{command:02X}"
        )

    return data


# ============================================================
# Firmware Update
# ============================================================

def firmware_update():

    # --------------------------------------------------------
    # Read firmware
    # --------------------------------------------------------

    with open(FIRMWARE_FILE, "rb") as file:
        firmware = file.read()

    firmware_size = len(firmware)

    print()
    print("=" * 60)
    print(" STM32 BOOTLOADER FIRMWARE UPDATE")
    print("=" * 60)

    print(
        f"Firmware size : {firmware_size} bytes "
        f"({firmware_size / 1024:.2f} KB)"
    )

    print(
        f"App address   : 0x{APP_START_ADDRESS:08X}"
    )

    # --------------------------------------------------------
    # Calculate firmware CRC
    # --------------------------------------------------------

    firmware_crc = crc16_ccitt_false(firmware)

    print(
        f"Firmware CRC  : 0x{firmware_crc:04X}"
    )

    # --------------------------------------------------------
    # Open serial
    # --------------------------------------------------------

    ser = serial.Serial(
        PORT,
        BAUDRATE,
        timeout=0.5
    )

    time.sleep(0.1)

    print()
    print("Serial connected.")

    # ========================================================
    # 1. SYNC
    # ========================================================

    print()
    print("[1] Sending SYNC...")

    send_packet(
        ser,
        CMD_SYNC
    )

    wait_for_ack(ser)

    print("SYNC ACK")

    # ========================================================
    # 2. DEVICE ID
    # ========================================================

    print()
    print("[2] Requesting Device ID...")

    send_packet(
        ser,
        CMD_DEVICE_ID_REQ
    )

    device_id = wait_for_command(
        ser,
        CMD_DEVICE_ID_RES
    )

    print(
        "Device ID:",
        device_id.hex(" ")
    )

    # ========================================================
    # 3. Firmware Size
    # ========================================================

    print()
    print("[3] Sending firmware size...")

    size_data = struct.pack(
        "<I",
        firmware_size
    )

    send_packet(
        ser,
        CMD_FW_SIZE,
        size_data
    )

    wait_for_ack(ser)

    print("Firmware size accepted.")

    # ========================================================
    # 4. Application Start Address
    # ========================================================

    print()
    print("[4] Sending application start address...")

    address_data = struct.pack(
        "<I",
        APP_START_ADDRESS
    )

    send_packet(
        ser,
        CMD_SET_APP_START_ADDRESS,
        address_data
    )

    wait_for_ack(ser)

    print("Application address accepted.")

    # ========================================================
    # 5. Firmware Data
    # ========================================================

    print()
    print("[5] Sending firmware data...")

    offset = 0
    packet_number = 0

    while offset < firmware_size:

        chunk = firmware[
            offset:
            offset + MAX_DATA_SIZE
        ]

        packet_number += 1

        print(
            f"\nPacket {packet_number}: "
            f"offset={offset} "
            f"length={len(chunk)}"
        )

        send_packet(
            ser,
            CMD_FW_DATA,
            chunk
        )

        # ----------------------------------------------
        # Last packet
        # ----------------------------------------------

        if offset + len(chunk) == firmware_size:

            wait_for_command(
                ser,
                CMD_UPDATE_SUCCESSFUL
            )

            print(
                "Firmware data transmission COMPLETE."
            )

        else:

            wait_for_ack(ser)

        offset += len(chunk)

        progress = (
            offset * 100.0 /
            firmware_size
        )

        print(
            f"Progress: {progress:.1f}%"
        )

    # ========================================================
    # 6. CRC CHECK
    # ========================================================

    print()
    print("[6] Sending CRC CHECK...")

    # Bootloader currently expects:
    # data[0] = CRC MSB
    # data[1] = CRC LSB

    crc_data = struct.pack(
        ">H",
        firmware_crc
    )

    send_packet(
        ser,
        CMD_CRC_CHECK,
        crc_data
    )

    wait_for_ack(ser)

    print()
    print("=" * 60)
    print(" FIRMWARE CRC VERIFIED SUCCESSFULLY")
    print("=" * 60)

    ser.close()


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":

    try:

        firmware_update()

    except FileNotFoundError:

        print(
            f"ERROR: Firmware file "
            f"'{FIRMWARE_FILE}' not found."
        )

    except serial.SerialException as e:

        print(
            f"Serial ERROR: {e}"
        )

    except Exception as e:

        print(
            f"ERROR: {e}"
        )

    finally:

        print()
        input("Press Enter to exit...")