
import serial
import time


# ==============================================================
# Configuration
# ==============================================================

PORT = "COM11"          # Change this
BAUDRATE = 115200

TIMEOUT = 6.0


# ==============================================================
# Bootloader Protocol
# ==============================================================

BL_PROTOCOL_SOF = 0xA5

BL_PACKET_TYPE_COMMAND = 0x01


# --------------------------------------------------------------
# Commands
# --------------------------------------------------------------

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

BL_CMD_READY_FOR_DATA         = 0x48

BL_CMD_UPDATE_SUCCESSFUL      = 0x54

BL_CMD_ACK                    = 0x15
BL_CMD_NACK                   = 0x59
BL_CMD_RETX                   = 0x19


# ==============================================================
# CRC16-CCITT-FALSE
#
# Polynomial : 0x1021
# Initial    : 0xFFFF
# Input       : LENGTH + TYPE + COMMAND + DATA
# ==============================================================
def crc16_ccitt_false(data):

    crc = 0xFFFF

    for byte in data:

        crc ^= byte << 8

        for _ in range(8):

            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF

    return crc


# ==============================================================
# Packet Builder
#
# Packet:
#
# [SOF]
# [LENGTH]
# [TYPE]
# [COMMAND]
# [DATA...]
# [CRC_H]
# [CRC_L]
#
# LENGTH = TYPE + COMMAND + DATA
# ==============================================================

def build_command_packet(command, data=b""):

    length = 2 + len(data)

    packet_without_crc = bytes([
        length,
        BL_PACKET_TYPE_COMMAND,
        command
    ]) + data

    crc = crc16_ccitt_false(packet_without_crc)

    packet = bytes([
        BL_PROTOCOL_SOF
    ]) + packet_without_crc + bytes([
        (crc >> 8) & 0xFF,
        crc & 0xFF
    ])

    return packet


# ==============================================================
# Packet Receiver
# ==============================================================

def receive_packet(ser):

    # Wait for SOF
    while True:

        byte = ser.read(1)

        if not byte:
            raise TimeoutError("Timeout waiting for SOF")

        if byte[0] == BL_PROTOCOL_SOF:
            break


    # LENGTH
    length_byte = ser.read(1)

    if len(length_byte) != 1:
        raise TimeoutError("Timeout waiting for LENGTH")

    length = length_byte[0]


    # TYPE + COMMAND + DATA
    payload = ser.read(length)

    if len(payload) != length:
        raise TimeoutError("Timeout waiting for payload")


    # CRC
    crc_bytes = ser.read(2)

    if len(crc_bytes) != 2:
        raise TimeoutError("Timeout waiting for CRC")


    received_crc = (
        (crc_bytes[0] << 8) |
        crc_bytes[1]
    )


    # CRC is calculated over:
    #
    # LENGTH + TYPE + COMMAND + DATA
    #
    crc_data = bytes([length]) + payload

    calculated_crc = crc16_ccitt_false(crc_data)


    if received_crc != calculated_crc:

        print(
            f"[ERROR] CRC mismatch: "
            f"RX=0x{received_crc:04X}, "
            f"CALC=0x{calculated_crc:04X}"
        )

        return None


    packet_type = payload[0]
    command = payload[1]
    data = payload[2:]


    return {
        "length": length,
        "type": packet_type,
        "command": command,
        "data": data
    }


# ==============================================================
# Send Packet
# ==============================================================

def send_packet(ser, packet):

    print(
        "[PC → MCU]",
        packet.hex(" ").upper()
    )

    ser.write(packet)
    ser.flush()


# ==============================================================
# Receive and Print
# ==============================================================

def receive_and_print(ser):

    packet = receive_packet(ser)

    if packet is None:
        return None


    print(
        "[MCU → PC]"
        f" CMD=0x{packet['command']:02X}"
        f" DATA={packet['data'].hex(' ').upper()}"
    )

    return packet


# ==============================================================
# Expect Command
# ==============================================================

def expect_command(ser, expected_command):

    packet = receive_and_print(ser)

    if packet is None:
        return False


    if packet["command"] != expected_command:

        print(
            f"[ERROR] Expected "
            f"0x{expected_command:02X}, "
            f"received "
            f"0x{packet['command']:02X}"
        )

        return False


    print(
        f"[OK] Received expected command "
        f"0x{expected_command:02X}"
    )

    return True


# ==============================================================
# Main RETX Test
# ==============================================================

def main():

    print()
    print("==========================================")
    print(" STM32 Bootloader RETX Test")
    print("==========================================")
    print()


    with serial.Serial(
        port=PORT,
        baudrate=BAUDRATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=TIMEOUT
    ) as ser:

        # ------------------------------------------------------
        # Clear old data
        # ------------------------------------------------------

        ser.reset_input_buffer()
        ser.reset_output_buffer()


        # ======================================================
        # 1. SYNC
        # ======================================================

        print("[TEST 1] SYNC")

        packet = build_command_packet(
            BL_CMD_SYNC_OBSERVED
        )

        send_packet(ser, packet)

        if not expect_command(
            ser,
            BL_CMD_ACK
        ):
            return


        # ======================================================
        # 2. DEVICE ID REQUEST
        # ======================================================

        print()
        print("[TEST 2] DEVICE ID REQUEST")

        packet = build_command_packet(
            BL_CMD_DEVICE_ID_REQ
        )

        send_packet(ser, packet)

        device_id_packet = receive_and_print(ser)

        if device_id_packet is None:
            return


        if device_id_packet["command"] != BL_CMD_DEVICE_ID_RES:

            print("[ERROR] DEVICE_ID_RES expected")
            return


        print("[OK] Device ID received")


        # ======================================================
        # 3. FW SIZE
        # ======================================================

        print()
        print("[TEST 3] FW SIZE")

        firmware_size = 1024

        firmware_size_data = firmware_size.to_bytes(
            4,
            byteorder="little"
        )


        packet = build_command_packet(
            BL_CMD_FW_SIZE,
            firmware_size_data
        )

        send_packet(ser, packet)


        if not expect_command(
            ser,
            BL_CMD_ACK
        ):
            return


        # ======================================================
        # 4. SET APPLICATION START ADDRESS
        # ======================================================

        print()
        print("[TEST 4] SET APP START ADDRESS")


        app_start_address = 0x08008000


        address_data = app_start_address.to_bytes(
            4,
            byteorder="little"
        )


        packet = build_command_packet(
            BL_CMD_SET_APP_START_ADDRESS,
            address_data
        )


        send_packet(ser, packet)


        if not expect_command(
            ser,
            BL_CMD_ACK
        ):
            return


        print()
        print(
            f"[INFO] App Start Address = "
            f"0x{app_start_address:08X}"
        )


        # ======================================================
        # 5. RETX TEST
        # ======================================================

        print()
        print("[TEST 5] RETX")
        print(
            "[INFO] Requesting MCU to re-process "
            "the previous packet..."
        )


        retx_packet = build_command_packet(
            BL_CMD_RETX
        )


        send_packet(ser, retx_packet)


        if not expect_command(
            ser,
            BL_CMD_ACK
        ):
            return


        print()
        print("==========================================")
        print(" RETX TEST PASSED")
        print("==========================================")
        print()


# ==============================================================
# Entry Point
# ==============================================================

if __name__ == "__main__":

    try:
        main()

    except serial.SerialException as e:

        print()
        print("[SERIAL ERROR]")
        print(e)

    except TimeoutError as e:

        print()
        print("[TIMEOUT]")
        print(e)

    except KeyboardInterrupt:

        print()
        print()
        print("Test interrupted by user.")



