import serial
import time
import struct


# ==============================================================
# Configuration
# ==============================================================

PORT = "COM9"
BAUDRATE = 115200
TIMEOUT = 1.0


# ==============================================================
# Protocol
# ==============================================================

BL_PROTOCOL_SOF = 0xA5

BL_PACKET_TYPE_COMMAND = 0x01
BL_PACKET_TYPE_DATA    = 0x02


# Commands
BL_CMD_SYNC_OBSERVED         = 0x20
BL_CMD_FW_UPDATE_REQ         = 0x31
BL_CMD_FW_UPDATE_RES         = 0x37
BL_CMD_DEVICE_ID_REQ        = 0x3C
BL_CMD_DEVICE_ID_RES        = 0x3F
BL_CMD_FW_SIZE              = 0x42
BL_CMD_READY_FOR_DATA       = 0x48
BL_CMD_UPDATE_SUCCESSFUL    = 0x54
BL_CMD_ACK                  = 0x15
BL_CMD_NACK                 = 0x59
BL_CMD_RETX                 = 0x19
BL_CMD_SET_APP_START_ADDRESS = 0x4A


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


# ==============================================================
# CRC16-CCITT-FALSE
# ==============================================================
#
# Polynomial : 0x1021
# Initial    : 0xFFFF
# Input      : MSB first
#
# CRC is calculated over:
#
# LENGTH + TYPE + COMMAND + DATA
#
# SOF is excluded.
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
# ==============================================================

def create_command_data(
    command: int,
    data: bytes
) -> bytes:

    length = 2 + len(data)

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
# RX Buffer
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
        "PC -> MCU:",
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
    timeout=1.0
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

            if len(rx) >= 6:

                length = rx[1]

                total_length = (
                    1 + 1 + length + 2
                )

                if len(rx) >= total_length:

                    packet = bytes(
                        rx[:total_length]
                    )

                    print(
                        "MCU -> PC:",
                        " ".join(
                            f"{byte:02X}"
                            for byte in packet
                        )
                    )

                    return parse_packet(
                        packet
                    )

        time.sleep(0.005)

    print("MCU -> PC: TIMEOUT")

    return None


# ==============================================================
# Parse Packet
# ==============================================================

def parse_packet(
    packet: bytes
):

    if len(packet) < 6:

        print("Invalid packet length")

        return None

    if packet[0] != BL_PROTOCOL_SOF:

        print("Invalid SOF")

        return None

    length = packet[1]

    expected_length = (
        1 + 1 + length + 2
    )

    if len(packet) != expected_length:

        print(
            "Invalid frame length"
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
            f"RX=0x{received_crc:04X}, "
            f"CALC=0x{calculated_crc:04X}"
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
# Expect Command
# ==============================================================

def expect_command(
    packet,
    command
):

    if packet is None:

        print("FAIL: No valid packet")

        return False

    if packet["command"] != command:

        print(
            f"FAIL: Expected "
            f"CMD=0x{command:02X}, "
            f"got CMD=0x"
            f"{packet['command']:02X}"
        )

        return False

    print("PASS")

    return True


# ==============================================================
# Expect NACK + Error
# ==============================================================

def expect_nack(
    packet,
    error
):

    if packet is None:

        print(
            "FAIL: No NACK received"
        )

        return False

    if packet["command"] != BL_CMD_NACK:

        print(
            f"FAIL: Expected NACK, "
            f"got CMD=0x"
            f"{packet['command']:02X}"
        )

        return False

    if len(packet["data"]) != 1:

        print(
            "FAIL: NACK error data "
            "missing"
        )

        return False

    received_error = (
        packet["data"][0]
    )

    if received_error != error:

        print(
            f"FAIL: Expected ERROR="
            f"0x{error:02X}, "
            f"got ERROR="
            f"0x{received_error:02X}"
        )

        return False

    print("PASS")

    return True


# ==============================================================
# Establish WAIT_FW_LENGTH
# ==============================================================
#
# SYNC:
# WAIT_SYNC -> CONNECTED
#
# DEVICE ID:
# CONNECTED -> WAIT_FW_LENGTH
# ==============================================================

def prepare_fw_length_state(ser):

    print(
        "\nPreparing "
        "WAIT_FW_LENGTH state..."
    )

    # SYNC
    clear_rx(ser)

    packet = create_command(
        BL_CMD_SYNC_OBSERVED
    )

    send_packet(
        ser,
        packet
    )

    response = receive_packet(
        ser
    )

    if not expect_command(
        response,
        BL_CMD_ACK
    ):

        return False

    # DEVICE ID
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

    if not expect_command(
        response,
        BL_CMD_DEVICE_ID_RES
    ):

        return False

    print(
        "Firmware-size state ready."
    )

    return True


# ==============================================================
# TEST 1
# ==============================================================

def test_sync(ser):

    print("\n========================================")
    print("TEST 1: SYNC")
    print("========================================")

    clear_rx(ser)

    packet = create_command(
        BL_CMD_SYNC_OBSERVED
    )

    send_packet(
        ser,
        packet
    )

    response = receive_packet(
        ser
    )

    return expect_command(
        response,
        BL_CMD_ACK
    )


# ==============================================================
# TEST 2
# ==============================================================

def test_device_id(ser):

    print("\n========================================")
    print("TEST 2: DEVICE ID")
    print("========================================")

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

    if not expect_command(
        response,
        BL_CMD_DEVICE_ID_RES
    ):

        return False

    print(
        "Device ID:",
        " ".join(
            f"{byte:02X}"
            for byte in response["data"]
        )
    )

    if len(response["data"]) != 12:

        print(
            "FAIL: Device ID must "
            "contain 12 bytes"
        )

        return False

    print("PASS")

    return True


# ==============================================================
# TEST 3
# ==============================================================

def test_fw_size(ser):

    print("\n========================================")
    print("TEST 3: FIRMWARE SIZE")
    print("========================================")

    clear_rx(ser)

    firmware_size = 2048

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

    response = receive_packet(
        ser
    )

    return expect_command(
        response,
        BL_CMD_ACK
    )


# ==============================================================
# TEST 4
# ==============================================================

def test_start_address(ser):

    print("\n========================================")
    print("TEST 4: START ADDRESS")
    print("========================================")

    clear_rx(ser)

    start_address = 0x08008000

    data = struct.pack(
        "<I",
        start_address
    )

    packet = create_command_data(
        BL_CMD_SET_APP_START_ADDRESS,
        data
    )

    send_packet(
        ser,
        packet
    )

    response = receive_packet(
        ser
    )

    return expect_command(
        response,
        BL_CMD_ACK
    )


# ==============================================================
# TEST 5
# ==============================================================

def test_retx(ser):

    print("\n========================================")
    print("TEST 5: RETX")
    print("========================================")

    clear_rx(ser)

    packet = create_command(
        BL_CMD_RETX
    )

    send_packet(
        ser,
        packet
    )

    response = receive_packet(
        ser
    )

    return expect_command(
        response,
        BL_CMD_ACK
    )


# ==============================================================
# TEST 6
# ==============================================================
#
# CRC error should NOT change bootloader state.
#
# Current state before this test:
#
# BL_STATE_READY
#
# We corrupt CRC of a command packet.
#
# Expected:
#
# NACK + BL_ERROR_CRC
#
# State should remain READY.
# ==============================================================

def test_crc_error(ser):

    print("\n========================================")
    print("TEST 6: CRC ERROR")
    print("========================================")

    clear_rx(ser)

    packet = bytearray(
        create_command(
            BL_CMD_RETX
        )
    )

    # Corrupt CRC
    packet[-1] ^= 0xFF

    send_packet(
        ser,
        bytes(packet)
    )

    response = receive_packet(
        ser
    )

    return expect_nack(
        response,
        BL_ERROR_CRC
    )


# ==============================================================
# TEST 7
# ==============================================================
#
# Need WAIT_FW_LENGTH first.
#
# Invalid firmware size should reach
# BL_ERROR_SIZE validation.
# ==============================================================

def test_invalid_fw_size(ser):

    print("\n========================================")
    print("TEST 7: INVALID FW SIZE")
    print("========================================")

    if not prepare_fw_length_state(
        ser
    ):

        print(
            "FAIL: Could not prepare "
            "WAIT_FW_LENGTH state"
        )

        return False

    clear_rx(ser)

    firmware_size = 0xFFFFFFFF

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

    response = receive_packet(
        ser
    )

    return expect_nack(
        response,
        BL_ERROR_SIZE
    )


# ==============================================================
# TEST 8
# ==============================================================
#
# Need WAIT_FW_START_ADDRESS first.
#
# So:
#
# SYNC
# DEVICE ID
# Valid FW SIZE
# Invalid address
# ==============================================================

def test_invalid_address(ser):

    print("\n========================================")
    print("TEST 8: INVALID START ADDRESS")
    print("========================================")

    if not prepare_fw_length_state(
        ser
    ):

        print(
            "FAIL: Could not prepare "
            "WAIT_FW_LENGTH state"
        )

        return False

    # Send valid firmware size
    clear_rx(ser)

    firmware_size = 1024

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

    response = receive_packet(
        ser
    )

    if not expect_command(
        response,
        BL_CMD_ACK
    ):

        return False

    # Now state should be:
    #
    # WAIT_FW_START_ADDRESS

    clear_rx(ser)

    invalid_address = 0x00000000

    data = struct.pack(
        "<I",
        invalid_address
    )

    packet = create_command_data(
        BL_CMD_SET_APP_START_ADDRESS,
        data
    )

    send_packet(
        ser,
        packet
    )

    response = receive_packet(
        ser
    )

    return expect_nack(
        response,
        BL_ERROR_ADDRESS
    )


# ==============================================================
# TEST 9
# ==============================================================

def test_unknown_command(ser):

    print("\n========================================")
    print("TEST 9: UNKNOWN COMMAND")
    print("========================================")

    clear_rx(ser)

    packet = create_command(
        0x99
    )

    send_packet(
        ser,
        packet
    )

    response = receive_packet(
        ser
    )

    return expect_nack(
        response,
        BL_ERROR_COMMAND
    )


# ==============================================================
# MAIN
# ==============================================================

def main():

    print("\n")
    print("========================================")
    print(" STM32 BOOTLOADER VALIDATION")
    print("========================================")

    print(
        f"Port     : {PORT}"
    )

    print(
        f"Baudrate : {BAUDRATE}"
    )

    try:

        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            timeout=0.05
        )

    except Exception as error:

        print(
            f"\nERROR: Cannot open "
            f"serial port: {error}"
        )

        return

    try:

        results = []

        # ------------------------------------------------------
        # Main normal-flow tests
        # ------------------------------------------------------

        results.append(
            test_sync(ser)
        )

        results.append(
            test_device_id(ser)
        )

        results.append(
            test_fw_size(ser)
        )

        results.append(
            test_start_address(ser)
        )

        results.append(
            test_retx(ser)
        )

        # ------------------------------------------------------
        # CRC error
        # ------------------------------------------------------

        results.append(
            test_crc_error(ser)
        )

        # ------------------------------------------------------
        # Negative tests
        # ------------------------------------------------------

        results.append(
            test_invalid_fw_size(ser)
        )

        results.append(
            test_invalid_address(ser)
        )

        results.append(
            test_unknown_command(ser)
        )

        # ------------------------------------------------------
        # Final result
        # ------------------------------------------------------

        print("\n")
        print("========================================")
        print(" FINAL RESULT")
        print("========================================")

        passed = sum(results)
        total = len(results)

        print(
            f"Passed: {passed}/{total}"
        )

        if passed == total:

            print(
                "\nALL TESTS PASSED"
            )

        else:

            print(
                "\nSOME TESTS FAILED"
            )

    finally:

        ser.close()


# ==============================================================
# Entry Point
# ==============================================================

if __name__ == "__main__":

    main()