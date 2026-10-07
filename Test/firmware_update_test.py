import serial
import time
import struct
from pathlib import Path


# ==============================================================
# Configuration
# ==============================================================

PORT = "COM7"
BAUDRATE = 115200
TIMEOUT = 10.0

# Application start address
APP_START_ADDRESS = 0x08004000

# Maximum firmware data per protocol packet
MAX_DATA_SIZE = 16

# Firmware file
# The script searches for the .bin file automatically
# in the same directory and its parent directory.
SCRIPT_DIR = Path(__file__).resolve().parent


def find_firmware_file():
    """
    Find firmware .bin automatically.

    Priority:
        1. firmware.bin
        2. PROJECT_NAME.bin
        3. First .bin file found
    """

    candidates = [
        SCRIPT_DIR / "firmware.bin",
        SCRIPT_DIR.parent / "firmware.bin",
    ]

    for file in candidates:
        if file.exists():
            return file

    # Search .bin files in script directory
    bin_files = list(SCRIPT_DIR.glob("*.bin"))

    if len(bin_files) == 1:
        return bin_files[0]

    # Search .bin files in parent directory
    bin_files = list(SCRIPT_DIR.parent.glob("*.bin"))

    if len(bin_files) == 1:
        return bin_files[0]

    return None


FIRMWARE_FILE = find_firmware_file()


# ==============================================================
# Protocol
# ==============================================================

BL_PROTOCOL_SOF = 0xA5

BL_PACKET_TYPE_COMMAND = 0x01
BL_PACKET_TYPE_DATA = 0x02


# ==============================================================
# Commands
# ==============================================================

BL_CMD_NONE                    = 0x00
BL_CMD_SYNC_OBSERVED          = 0x20
BL_CMD_FW_UPDATE_REQ          = 0x31
BL_CMD_FW_UPDATE_RES          = 0x37
BL_CMD_DEVICE_ID_REQ          = 0x3C
BL_CMD_DEVICE_ID_RES          = 0x3F
BL_CMD_FW_SIZE                = 0x42
BL_CMD_FW_OVER_SIZE           = 0x45
BL_CMD_SET_APP_START_ADDRESS  = 0x4A
BL_CMD_APP_START_ADDRESS_ERROR = 0x4B
BL_CMD_FW_DATA                = 0x50
BL_CMD_READY_FOR_DATA         = 0x48
BL_CMD_UPDATE_SUCCESSFUL      = 0x54
BL_CMD_ACK                    = 0x15
BL_CMD_NACK                   = 0x59
BL_CMD_RETX                   = 0x19
BL_CMD_CRC_CHECK              = 0x3B


# ==============================================================
# Error Codes
# ==============================================================

BL_ERROR_NONE            = 0x00
BL_ERROR_CRC             = 0x01
BL_ERROR_LENGTH          = 0x02
BL_ERROR_COMMAND         = 0x03
BL_ERROR_STATE           = 0x04
BL_ERROR_ADDRESS         = 0x05
BL_ERROR_SIZE            = 0x06
BL_ERROR_PROTOCOL        = 0x07
BL_ERROR_DEVICE_ID       = 0x08
BL_ERROR_NO_RETRY_PACKET = 0x09
BL_ERROR_FLASH_ERASE     = 0x0A
BL_ERROR_DATA            = 0x0B


# ==============================================================
# CRC16-CCITT-FALSE
#
# Polynomial : 0x1021
# Initial    : 0xFFFF
# Input      : MSB first
#
# IMPORTANT:
#
# CRC is calculated over:
#
#     LENGTH + TYPE + COMMAND + DATA
#
# SOF is NOT included.
#
# CRC is transmitted Big-Endian.
# ==============================================================

def crc16_ccitt_false(data: bytes) -> int:

    crc = 0xFFFF

    for byte in data:

        crc ^= (byte << 8)

        for _ in range(8):

            if crc & 0x8000:

                crc = (
                    (crc << 1) ^ 0x1021
                ) & 0xFFFF

            else:

                crc = (
                    crc << 1
                ) & 0xFFFF

    return crc


# ==============================================================
# Create Command Packet
#
# Frame:
#
# SOF | LENGTH | TYPE | COMMAND | CRC_H | CRC_L
#
# Example:
#
# A5 02 01 20 XX XX
# ==============================================================

def create_command(command: int) -> bytes:

    length = 2

    body = bytes([
        length,
        BL_PACKET_TYPE_COMMAND,
        command
    ])

    crc = crc16_ccitt_false(body)

    return (
        bytes([BL_PROTOCOL_SOF])
        + body
        + struct.pack(">H", crc)
    )


# ==============================================================
# Create Command + Data Packet
#
# Frame:
#
# SOF | LENGTH | TYPE | COMMAND | DATA | CRC_H | CRC_L
# ==============================================================

def create_command_data(
    command: int,
    data: bytes
) -> bytes:

    length = 2 + len(data)

    if length > (MAX_DATA_SIZE + 2):
        raise ValueError(
            "Command data is too large"
        )

    body = bytes([
        length,
        BL_PACKET_TYPE_COMMAND,
        command
    ]) + data

    crc = crc16_ccitt_false(body)

    return (
        bytes([BL_PROTOCOL_SOF])
        + body
        + struct.pack(">H", crc)
    )


# ==============================================================
# Create Firmware Data Packet
#
# TYPE = DATA
#
# Frame:
#
# SOF | LENGTH | TYPE | COMMAND | DATA | CRC_H | CRC_L
# ==============================================================

def create_firmware_data(
    data: bytes
) -> bytes:

    if len(data) == 0:
        raise ValueError(
            "Firmware data cannot be empty"
        )

    if len(data) > MAX_DATA_SIZE:
        raise ValueError(
            "Firmware data exceeds 16 bytes"
        )

    length = 2 + len(data)

    body = bytes([
        length,
        BL_PACKET_TYPE_DATA,
        BL_CMD_FW_DATA
    ]) + data

    crc = crc16_ccitt_false(body)

    return (
        bytes([BL_PROTOCOL_SOF])
        + body
        + struct.pack(">H", crc)
    )


# ==============================================================
# Clear RX Buffer
# ==============================================================

def clear_rx(ser):

    time.sleep(0.05)

    while ser.in_waiting:

        ser.read(ser.in_waiting)


# ==============================================================
# Send Packet
# ==============================================================

def send_packet(
    ser,
    packet: bytes
):

    print(
        "[TX]",
        " ".join(
            f"{byte:02X}"
            for byte in packet
        )
    )

    ser.write(packet)
    ser.flush()


# ==============================================================
# Receive Packet
# ==============================================================

def receive_packet(
    ser,
    timeout=10.0
):

    start_time = time.time()

    rx = bytearray()

    while (
        time.time() - start_time
    ) < timeout:

        if ser.in_waiting:

            rx.extend(
                ser.read(
                    ser.in_waiting
                )
            )

            # Need at least:
            #
            # SOF + LENGTH + TYPE + CMD + CRC
            #
            if len(rx) >= 6:

                # Find SOF
                try:
                    sof_index = rx.index(
                        BL_PROTOCOL_SOF
                    )
                except ValueError:
                    rx.clear()
                    continue

                if sof_index > 0:

                    del rx[:sof_index]

                if len(rx) < 2:
                    continue

                length = rx[1]

                total_length = (
                    1 + 1 + length + 2
                )

                if len(rx) >= total_length:

                    packet = bytes(
                        rx[:total_length]
                    )

                    print(
                        "[RX]",
                        " ".join(
                            f"{byte:02X}"
                            for byte in packet
                        )
                    )

                    return parse_packet(
                        packet
                    )

        time.sleep(0.005)

    print("[RX] TIMEOUT")

    return None


# ==============================================================
# Parse Packet
# ==============================================================

def parse_packet(
    packet: bytes
):

    if len(packet) < 6:

        print(
            "ERROR: Invalid packet length"
        )

        return None

    if packet[0] != BL_PROTOCOL_SOF:

        print(
            "ERROR: Invalid SOF"
        )

        return None

    length = packet[1]

    expected_length = (
        1 + 1 + length + 2
    )

    if len(packet) != expected_length:

        print(
            "ERROR: Invalid frame length"
        )

        return None

    received_crc = struct.unpack(
        ">H",
        packet[-2:]
    )[0]

    calculated_crc = crc16_ccitt_false(
        packet[1:-2]
    )

    if received_crc != calculated_crc:

        print(
            f"CRC ERROR: "
            f"received=0x{received_crc:04X} "
            f"calculated=0x{calculated_crc:04X}"
        )

        return None

    return {
        "sof": packet[0],
        "length": packet[1],
        "type": packet[2],
        "command": packet[3],
        "data": packet[4:-2],
        "crc": received_crc
    }


# ==============================================================
# Wait For Specific Command
# ==============================================================

def wait_for_command(
    ser,
    expected_command: int,
    timeout=10.0
):

    packet = receive_packet(
        ser,
        timeout
    )

    if packet is None:

        return None

    if packet["command"] != expected_command:

        print(
            f"ERROR: Expected CMD=0x"
            f"{expected_command:02X}, "
            f"got CMD=0x"
            f"{packet['command']:02X}"
        )

        return None

    return packet


# ==============================================================
# Wait For ACK
# ==============================================================

def wait_for_ack(
    ser,
    timeout=10.0
):

    packet = receive_packet(
        ser,
        timeout
    )

    if packet is None:

        return False

    if packet["command"] == BL_CMD_ACK:

        print("ACK received")

        return True

    if packet["command"] == BL_CMD_NACK:

        if len(packet["data"]) > 0:

            error = packet["data"][0]

            print(
                f"NACK received: "
                f"ERROR=0x{error:02X}"
            )

        else:

            print(
                "NACK received"
            )

        return False

    print(
        f"Unexpected response: "
        f"CMD=0x{packet['command']:02X}"
    )

    return False


# ==============================================================
# Firmware CRC
#
# CRC is calculated over actual firmware bytes only.
#
# Padding bytes are NOT included.
# ==============================================================

def calculate_firmware_crc(
    firmware: bytes
) -> int:

    return crc16_ccitt_false(
        firmware
    )


# ==============================================================
# Send SYNC
# ==============================================================

def send_sync(ser):

    print(
        "\n[1] Sending SYNC..."
    )

    clear_rx(ser)

    packet = create_command(
        BL_CMD_SYNC_OBSERVED
    )

    send_packet(
        ser,
        packet
    )

    print("Waiting 5 seconds...")
    time.sleep(7)

    return wait_for_ack(
        ser
    )

    


# ==============================================================
# Request Device ID
# ==============================================================

def request_device_id(ser):

    print(
        "\n[2] Requesting Device ID..."
    )

    clear_rx(ser)

    packet = create_command(
        BL_CMD_DEVICE_ID_REQ
    )

    send_packet(
        ser,
        packet
    )

    response = receive_packet(
        ser
    )

    if response is None:

        return False

    if response["command"] != BL_CMD_DEVICE_ID_RES:

        print(
            f"ERROR: Expected DEVICE_ID_RES, "
            f"got CMD=0x"
            f"{response['command']:02X}"
        )

        return False

    device_id = response["data"]

    print(
        "Device ID:",
        " ".join(
            f"{byte:02X}"
            for byte in device_id
        )
    )

    if len(device_id) != 12:

        print(
            "ERROR: Device ID must contain "
            "12 bytes"
        )

        return False

    return True


# ==============================================================
# Send Firmware Size
# ==============================================================

def send_firmware_size(
    ser,
    firmware_size: int
):

    print(
        "\n[3] Sending firmware size..."
    )

    print(
        f"Firmware size: "
        f"{firmware_size} bytes"
    )

    clear_rx(ser)

    data = struct.pack(
        "<I",
        firmware_size
    )

    packet = create_command_data(
        BL_CMD_FW_SIZE,
        data
    )

    send_packet(
        ser,
        packet
    )

    return wait_for_ack(
        ser
    )


# ==============================================================
# Send Application Start Address
# ==============================================================

def send_start_address(ser):

    print(
        "\n[4] Sending application "
        "start address..."
    )

    print(
        f"App address: "
        f"0x{APP_START_ADDRESS:08X}"
    )

    clear_rx(ser)

    data = struct.pack(
        "<I",
        APP_START_ADDRESS
    )

    packet = create_command_data(
        BL_CMD_SET_APP_START_ADDRESS,
        data
    )

    send_packet(
        ser,
        packet
    )

    return wait_for_ack(
        ser
    )


# ==============================================================
# Send Firmware
# ==============================================================

def send_firmware(
    ser,
    firmware: bytes
):

    print(
        "\n[5] Sending firmware..."
    )

    total_size = len(firmware)

    offset = 0

    packet_number = 0

    while offset < total_size:

        chunk = firmware[
            offset:
            offset + MAX_DATA_SIZE
        ]

        packet_number += 1

        print(
            f"\nPacket {packet_number}: "
            f"{offset}/{total_size} "
            f"({len(chunk)} bytes)"
        )

        packet = create_firmware_data(
            chunk
        )

        send_packet(
            ser,
            packet
        )

        response = receive_packet(
            ser
        )

        if response is None:

            print(
                "ERROR: No response "
                "from bootloader"
            )

            return False

        # ------------------------------------------------------
        # Final packet
        # ------------------------------------------------------

        if (
            offset + len(chunk)
            >= total_size
        ):

            if (
                response["command"]
                != BL_CMD_UPDATE_SUCCESSFUL
            ):

                print(
                    "ERROR: Expected "
                    "UPDATE_SUCCESSFUL "
                    f"(0x{BL_CMD_UPDATE_SUCCESSFUL:02X}), "
                    f"got 0x"
                    f"{response['command']:02X}"
                )

                return False

            print(
                "Firmware data transfer "
                "completed."
            )

        # ------------------------------------------------------
        # Normal packet
        # ------------------------------------------------------

        else:

            if (
                response["command"]
                != BL_CMD_ACK
            ):

                if (
                    response["command"]
                    == BL_CMD_NACK
                ):

                    error = (
                        response["data"][0]
                        if len(response["data"]) > 0
                        else 0xFF
                    )

                    print(
                        f"ERROR: NACK "
                        f"0x{error:02X}"
                    )

                else:

                    print(
                        "ERROR: Unexpected "
                        f"response 0x"
                        f"{response['command']:02X}"
                    )

                return False

        offset += len(chunk)

        progress = (
            offset * 100
        ) // total_size

        print(
            f"Progress: "
            f"{progress}%"
        )

    return True


# ==============================================================
# Send Firmware CRC
#
# C bootloader expects:
#
# expected_crc =
#     ((uint16_t)data[0] << 8U) |
#     data[1];
#
# Therefore send Big-Endian.
# ==============================================================

def send_firmware_crc(
    ser,
    firmware_crc: int
):

    print(
        "\n[6] Sending firmware CRC..."
    )

    print(
        f"Firmware CRC: "
        f"0x{firmware_crc:04X}"
    )

    clear_rx(ser)

    data = struct.pack(
        ">H",
        firmware_crc
    )

    packet = create_command_data(
        BL_CMD_CRC_CHECK,
        data
    )

    send_packet(
        ser,
        packet
    )

    if wait_for_ack(ser):

        print(
            "Firmware CRC verification "
            "PASSED."
        )

        return True

    print(
        "Firmware CRC verification "
        "FAILED."
    )

    return False


# ==============================================================
# Main Firmware Update
# ==============================================================

def main():

    print()
    print("=" * 60)
    print(
        " STM32 BOOTLOADER FIRMWARE UPDATE"
    )
    print("=" * 60)

    # ----------------------------------------------------------
    # Firmware file
    # ----------------------------------------------------------

    if FIRMWARE_FILE is None:

        print()
        print(
            "ERROR: No firmware .bin file found."
        )

        print(
            "Place the .bin file in:"
        )

        print(
            f"    {SCRIPT_DIR}"
        )

        print(
            "or:"
        )

        print(
            f"    {SCRIPT_DIR.parent}"
        )

        input(
            "\nPress Enter to exit..."
        )

        return

    print(
        f"Firmware file : "
        f"{FIRMWARE_FILE}"
    )

    # ----------------------------------------------------------
    # Read firmware
    # ----------------------------------------------------------

    try:

        with open(
            FIRMWARE_FILE,
            "rb"
        ) as file:

            firmware = file.read()

    except Exception as error:

        print(
            f"ERROR: Cannot read firmware: "
            f"{error}"
        )

        input(
            "\nPress Enter to exit..."
        )

        return

    firmware_size = len(firmware)

    if firmware_size == 0:

        print(
            "ERROR: Firmware file is empty."
        )

        input(
            "\nPress Enter to exit..."
        )

        return

    # ----------------------------------------------------------
    # Calculate firmware CRC
    # ----------------------------------------------------------

    firmware_crc = calculate_firmware_crc(
        firmware
    )

    print(
        f"Firmware size : "
        f"{firmware_size} bytes "
        f"({firmware_size / 1024:.2f} KB)"
    )

    print(
        f"App address   : "
        f"0x{APP_START_ADDRESS:08X}"
    )

    print(
        f"Firmware CRC  : "
        f"0x{firmware_crc:04X}"
    )

    # ----------------------------------------------------------
    # Open serial
    # ----------------------------------------------------------

    try:

        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            timeout=0.05
        )

    except Exception as error:

        print()
        print(
            f"ERROR: Cannot open serial port: "
            f"{error}"
        )

        input(
            "\nPress Enter to exit..."
        )

        return

    print()
    print(
        "Serial connected."
    )

    try:

        # ------------------------------------------------------
        # 1. SYNC
        # ------------------------------------------------------

        if not send_sync(ser):

            print(
                "\nERROR: SYNC failed."
            )

            return

        # ------------------------------------------------------
        # 2. DEVICE ID
        # ------------------------------------------------------

        if not request_device_id(ser):

            print(
                "\nERROR: Device ID request failed."
            )

            return

        # ------------------------------------------------------
        # 3. FIRMWARE SIZE
        # ------------------------------------------------------

        if not send_firmware_size(
            ser,
            firmware_size
        ):

            print(
                "\nERROR: Firmware size rejected."
            )

            return

        # ------------------------------------------------------
        # 4. START ADDRESS
        # ------------------------------------------------------

        if not send_start_address(ser):

            print(
                "\nERROR: Application start "
                "address rejected."
            )

            return

        # ------------------------------------------------------
        # 5. FIRMWARE DATA
        # ------------------------------------------------------

        if not send_firmware(
            ser,
            firmware
        ):

            print(
                "\nERROR: Firmware transfer failed."
            )

            return

        # ------------------------------------------------------
        # 6. FIRMWARE CRC
        # ------------------------------------------------------

        if not send_firmware_crc(
            ser,
            firmware_crc
        ):

            print(
                "\nERROR: Firmware verification failed."
            )

            return

        # ------------------------------------------------------
        # SUCCESS
        # ------------------------------------------------------

        print()
        print("=" * 60)
        print(
            " FIRMWARE UPDATE SUCCESSFUL"
        )
        print("=" * 60)
        print(
            f"Firmware size : "
            f"{firmware_size} bytes"
        )
        print(
            f"Firmware CRC  : "
            f"0x{firmware_crc:04X}"
        )
        print(
            f"App address   : "
            f"0x{APP_START_ADDRESS:08X}"
        )
        print("=" * 60)

    finally:

        ser.close()

        print(
            "\nSerial disconnected."
        )


# ==============================================================
# Entry Point
# ==============================================================

if __name__ == "__main__":

    main()

