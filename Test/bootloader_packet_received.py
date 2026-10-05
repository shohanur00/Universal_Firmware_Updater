import serial
import time


# ============================================================
# Configuration
# ============================================================

COM_PORT = "COM11"
BAUDRATE = 115200

SOF = 0xA5

BL_PACKET_TYPE_COMMAND = 0x01

BL_CMD_SYNC = 0x20
BL_CMD_ACK  = 0x15


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
# Create Command Packet
#
# [SOF] [LENGTH] [TYPE] [COMMAND] [CRC_H] [CRC_L]
# ============================================================

def create_command_packet(command):

    length = 2   # TYPE + COMMAND
    packet_type = BL_PACKET_TYPE_COMMAND

    crc_data = bytes([
        length,
        packet_type,
        command
    ])

    crc = crc16_ccitt_false(crc_data)

    frame = bytes([
        SOF,
        length,
        packet_type,
        command,
        (crc >> 8) & 0xFF,
        crc & 0xFF
    ])

    return frame


# ============================================================
# Hex Print
# ============================================================

def print_hex(label, data):
    print(f"{label}:")
    print(" ".join(f"{byte:02X}" for byte in data))


# ============================================================
# Main
# ============================================================

def main():

    print("========================================")
    print("       STM32 BOOTLOADER CHECK")
    print("========================================")
    print(f"Port     : {COM_PORT}")
    print(f"Baudrate : {BAUDRATE}")
    print()

    try:
        ser = serial.Serial(
            port=COM_PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1
        )

        print("[OK] Serial port opened")
        print()

    except serial.SerialException as e:

        print("[FAIL] Could not open serial port")
        print(e)
        return


    # Clear old data
    ser.reset_input_buffer()
    ser.reset_output_buffer()


    # --------------------------------------------------------
    # Create SYNC packet
    # --------------------------------------------------------

    packet = create_command_packet(BL_CMD_SYNC)

    print("TX:")
    print_hex("", packet)

    print()
    print("[OK] SYNC sent")

    ser.write(packet)
    ser.flush()


    # --------------------------------------------------------
    # Wait for response
    # --------------------------------------------------------

    print()
    print("Waiting for ACK...")
    print()

    start_time = time.time()

    rx = bytearray()

    while (time.time() - start_time) < 2.0:

        if ser.in_waiting:

            data = ser.read(ser.in_waiting)

            rx.extend(data)

            print_hex("RX", data)

        time.sleep(0.01)


    # --------------------------------------------------------
    # Result
    # --------------------------------------------------------

    print()

    if len(rx) == 0:

        print("[FAIL] No response received")

    elif BL_CMD_ACK in rx:

        print("[PASS] ACK received")

    else:

        print("[FAIL] Response received, but ACK not found")


    print()
    print("========================================")
    print("             TEST END")
    print("========================================")

    ser.close()


if __name__ == "__main__":
    main()