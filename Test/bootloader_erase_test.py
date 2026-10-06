
import serial
import time


# ============================================================
# STM32 BOOTLOADER TEST CONFIGURATION
# ============================================================

PORT = "COM9"
BAUDRATE = 115200

SERIAL_TIMEOUT = 0.05
RESPONSE_TIMEOUT = 5.0


# ============================================================
# Protocol
# ============================================================

BL_PROTOCOL_SOF = 0xA5

BL_PACKET_TYPE_COMMAND = 0x01


# ============================================================
# Commands
# ============================================================

BL_CMD_SYNC = 0x20
BL_CMD_DEVICE_ID_REQ = 0x3C
BL_CMD_DEVICE_ID_RES = 0x3F
BL_CMD_FW_SIZE = 0x42
BL_CMD_SET_APP_START_ADDRESS = 0x4A

BL_CMD_ACK = 0x15
BL_CMD_NACK = 0x59


# ============================================================
# Error Codes
# ============================================================

BL_ERROR_CRC = 0x01
BL_ERROR_LENGTH = 0x02
BL_ERROR_COMMAND = 0x03
BL_ERROR_STATE = 0x04
BL_ERROR_ADDRESS = 0x05
BL_ERROR_SIZE = 0x06
BL_ERROR_PROTOCOL = 0x07
BL_ERROR_DEVICE_ID = 0x08
BL_ERROR_NO_RETRY_PACKET = 0x09
BL_ERROR_FLASH_ERASE = 0x0A


# ============================================================
# Test Configuration
# ============================================================

FIRMWARE_SIZE = 8 * 1024

APP_START_ADDRESS = 0x08004000

FLASH_PAGE_SIZE = 2 * 1024

ERASE_SIZE = 108 * 1024


# ============================================================
# CRC16-CCITT-FALSE
#
# Polynomial : 0x1021
# Initial    : 0xFFFF
# RefIn      : False
# RefOut     : False
# XOROut     : 0x0000
# ============================================================

def crc16_ccitt_false(data):

    crc = 0xFFFF

    for byte in data:

        crc ^= (byte << 8)

        for _ in range(8):

            if crc & 0x8000:

                crc = (
                    (crc << 1) ^
                    0x1021
                ) & 0xFFFF

            else:

                crc = (
                    crc << 1
                ) & 0xFFFF

    return crc


# ============================================================
# Create Command Packet
#
# Frame:
#
# [SOF]
# [LENGTH]
# [TYPE]
# [COMMAND]
# [DATA...]
# [CRC_H]
# [CRC_L]
#
# CRC is calculated over:
#
# LENGTH + TYPE + COMMAND + DATA
# ============================================================

def create_command_packet(
    command,
    data=b""
):

    length = (
        2 +
        len(data)
    )

    frame = bytearray()

    frame.append(
        BL_PROTOCOL_SOF
    )

    frame.append(
        length
    )

    frame.append(
        BL_PACKET_TYPE_COMMAND
    )

    frame.append(
        command
    )

    frame.extend(
        data
    )

    # CRC excludes SOF
    crc = crc16_ccitt_false(
        frame[1:]
    )

    frame.append(
        (crc >> 8) & 0xFF
    )

    frame.append(
        crc & 0xFF
    )

    return bytes(frame)


# ============================================================
# Print Packet
# ============================================================

def print_packet(
    prefix,
    packet
):

    hex_data = " ".join(
        f"{byte:02X}"
        for byte in packet
    )

    print(
        f"{prefix}: {hex_data}"
    )


# ============================================================
# Receive Packet
# ============================================================

def receive_packet(
    ser,
    timeout=RESPONSE_TIMEOUT
):

    start_time = time.time()

    rx_buffer = bytearray()

    while (
        time.time() - start_time
    ) < timeout:

        if ser.in_waiting > 0:

            data = ser.read(
                ser.in_waiting
            )

            rx_buffer.extend(
                data
            )

            # ------------------------------------------------
            # Find SOF
            # ------------------------------------------------

            if BL_PROTOCOL_SOF not in rx_buffer:

                rx_buffer.clear()

                continue

            sof_index = rx_buffer.index(
                BL_PROTOCOL_SOF
            )

            if sof_index > 0:

                del rx_buffer[
                    :sof_index
                ]

            # ------------------------------------------------
            # Need SOF + LENGTH
            # ------------------------------------------------

            if len(rx_buffer) < 2:

                continue

            length = rx_buffer[1]

            # ------------------------------------------------
            # Total frame:
            #
            # SOF       = 1
            # LENGTH    = 1
            # payload   = LENGTH
            # CRC       = 2
            # ------------------------------------------------

            total_length = (
                1 +
                1 +
                length +
                2
            )

            if len(rx_buffer) < total_length:

                continue

            packet = bytes(
                rx_buffer[
                    :total_length
                ]
            )

            return packet

        time.sleep(
            0.001
        )

    return None


# ============================================================
# Send Packet and Receive Response
# ============================================================

def transact(
    ser,
    packet,
    timeout=RESPONSE_TIMEOUT
):

    print_packet(
        "PC -> MCU",
        packet
    )

    ser.reset_input_buffer()

    ser.write(
        packet
    )

    ser.flush()

    response = receive_packet(
        ser,
        timeout
    )

    if response is None:

        print(
            "MCU -> PC: TIMEOUT"
        )

        return None

    print_packet(
        "MCU -> PC",
        response
    )

    return response


# ============================================================
# Get Command
#
# Frame:
#
# [0] SOF
# [1] LENGTH
# [2] TYPE
# [3] COMMAND
# ============================================================

def get_command(
    response
):

    if response is None:

        return None

    if len(response) < 4:

        return None

    return response[3]


# ============================================================
# Get NACK Error
#
# NACK frame:
#
# [A5]
# [03]
# [01]
# [59]
# [ERROR]
# [CRC_H]
# [CRC_L]
# ============================================================

def get_nack_error(
    response
):

    if response is None:

        return None

    if len(response) < 5:

        return None

    if response[3] != BL_CMD_NACK:

        return None

    return response[4]


# ============================================================
# Check ACK
# ============================================================

def check_ack(
    response
):

    if response is None:

        print(
            "FAIL: No response"
        )

        return False

    command = get_command(
        response
    )

    if command == BL_CMD_ACK:

        print(
            "PASS"
        )

        return True

    if command == BL_CMD_NACK:

        error = get_nack_error(
            response
        )

        if error is not None:

            print(
                f"FAIL: NACK "
                f"ERROR=0x{error:02X}"
            )

        else:

            print(
                "FAIL: NACK received"
            )

        return False

    if command is not None:

        print(
            f"FAIL: Expected "
            f"CMD=0x{BL_CMD_ACK:02X}, "
            f"got CMD=0x{command:02X}"
        )

    else:

        print(
            "FAIL: Invalid response"
        )

    return False


# ============================================================
# Calculate Expected Flash Pages
# ============================================================

def calculate_flash_pages():

    start_page = (
        APP_START_ADDRESS -
        0x08000000
    ) // FLASH_PAGE_SIZE

    end_page = (
        (
            APP_START_ADDRESS +
            ERASE_SIZE -
            1
        ) -
        0x08000000
    ) // FLASH_PAGE_SIZE

    return (
        start_page,
        end_page
    )


# ============================================================
# Main Test
# ============================================================

def main():

    print()
    print("=" * 50)
    print(
        " STM32 BOOTLOADER 108KB FLASH ERASE TEST"
    )
    print("=" * 50)

    print(
        f"Port             : {PORT}"
    )

    print(
        f"Baudrate         : {BAUDRATE}"
    )

    print(
        f"Firmware Size    : {FIRMWARE_SIZE} bytes"
    )

    print(
        f"App Start        : "
        f"0x{APP_START_ADDRESS:08X}"
    )

    print(
        f"Erase Size       : "
        f"{ERASE_SIZE // 1024} KB"
    )

    start_page, end_page = (
        calculate_flash_pages()
    )

    print(
        f"Expected Pages   : "
        f"{start_page} -> {end_page}"
    )

    print()

    # ========================================================
    # Open Serial Port
    # ========================================================

    try:

        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            timeout=SERIAL_TIMEOUT
        )

    except serial.SerialException as error:

        print()
        print(
            f"ERROR: Cannot open {PORT}"
        )

        print(
            error
        )

        return

    time.sleep(
        0.2
    )

    passed = 0
    total = 4


    # ========================================================
    # TEST 1: SYNC
    # ========================================================

    print()
    print("=" * 50)
    print("TEST 1: SYNC")
    print("=" * 50)

    packet = create_command_packet(
        BL_CMD_SYNC
    )

    response = transact(
        ser,
        packet
    )

    if check_ack(response):

        passed += 1


    # ========================================================
    # TEST 2: DEVICE ID
    # ========================================================

    print()
    print("=" * 50)
    print("TEST 2: DEVICE ID")
    print("=" * 50)

    packet = create_command_packet(
        BL_CMD_DEVICE_ID_REQ
    )

    response = transact(
        ser,
        packet
    )

    if response is None:

        print(
            "FAIL: No response"
        )

    else:

        command = get_command(
            response
        )

        if command == BL_CMD_DEVICE_ID_RES:

            print(
                "PASS"
            )

            # Device ID:
            #
            # [SOF]
            # [LENGTH]
            # [TYPE]
            # [COMMAND]
            # [DEVICE ID]
            # [CRC_H]
            # [CRC_L]

            device_id = response[
                4:-2
            ]

            print(
                "Device ID: "
                +
                " ".join(
                    f"{byte:02X}"
                    for byte in device_id
                )
            )

            passed += 1

        elif command == BL_CMD_NACK:

            error = get_nack_error(
                response
            )

            print(
                f"FAIL: NACK "
                f"ERROR=0x{error:02X}"
            )

        else:

            print(
                f"FAIL: Expected "
                f"CMD=0x"
                f"{BL_CMD_DEVICE_ID_RES:02X}, "
                f"got CMD=0x{command:02X}"
            )


    # ========================================================
    # TEST 3: FIRMWARE SIZE
    # ========================================================

    print()
    print("=" * 50)
    print("TEST 3: FIRMWARE SIZE")
    print("=" * 50)

    firmware_size_data = (
        FIRMWARE_SIZE.to_bytes(
            4,
            byteorder="little"
        )
    )

    packet = create_command_packet(
        BL_CMD_FW_SIZE,
        firmware_size_data
    )

    response = transact(
        ser,
        packet
    )

    if check_ack(response):

        passed += 1


    # ========================================================
    # TEST 4: START ADDRESS
    #
    # MCU side:
    #
    # BL_Flash_Erase(
    #     start_address,
    #     108 * 1024
    # );
    #
    # Expected:
    #
    # Page 8 -> Page 61
    # ========================================================

    print()
    print("=" * 50)
    print(
        "TEST 4: START ADDRESS + 108KB FLASH ERASE"
    )
    print("=" * 50)

    print(
        f"Erase Size     : "
        f"{ERASE_SIZE // 1024} KB"
    )

    print(
        f"Expected Pages : "
        f"{start_page} -> {end_page}"
    )

    print(
        "Waiting for MCU..."
    )

    address_data = (
        APP_START_ADDRESS.to_bytes(
            4,
            byteorder="little"
        )
    )

    packet = create_command_packet(
        BL_CMD_SET_APP_START_ADDRESS,
        address_data
    )

    # Flash erase takes longer than
    # normal protocol response.

    response = transact(
        ser,
        packet,
        timeout=10.0
    )

    if response is None:

        print(
            "FAIL: No response from MCU"
        )

    else:

        command = get_command(
            response
        )

        # ----------------------------------------------------
        # ACK
        # ----------------------------------------------------

        if command == BL_CMD_ACK:

            print()
            print(
                "PASS: 108KB Flash erase successful"
            )

            passed += 1

        # ----------------------------------------------------
        # NACK
        # ----------------------------------------------------

        elif command == BL_CMD_NACK:

            error = get_nack_error(
                response
            )

            if error == BL_ERROR_FLASH_ERASE:

                print()
                print(
                    "FAIL: BL_ERROR_FLASH_ERASE"
                )

                print(
                    "Error Code: 0x0A"
                )

                print(
                    "Flash erase failed on MCU."
                )

            elif error is not None:

                print()
                print(
                    f"FAIL: NACK "
                    f"ERROR=0x{error:02X}"
                )

            else:

                print(
                    "FAIL: NACK received"
                )

        # ----------------------------------------------------
        # Unexpected response
        # ----------------------------------------------------

        else:

            print()
            print(
                f"FAIL: Unexpected "
                f"CMD=0x{command:02X}"
            )


    # ========================================================
    # FINAL RESULT
    # ========================================================

    print()
    print("=" * 50)
    print(" FINAL RESULT")
    print("=" * 50)

    print(
        f"Passed: {passed}/{total}"
    )

    if passed == total:

        print()
        print(
            "ALL TESTS PASSED"
        )

        print(
            "108KB Flash erase test successful."
        )

    else:

        print()
        print(
            "SOME TESTS FAILED"
        )

    print()

    ser.close()


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":

    main()
