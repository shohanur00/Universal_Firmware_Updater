
"""
Universal Firmware Updater
Modern Dark Engineering UI
Framework: PySide6

Features:
- COM port selection and refresh
- Repeated SYNC until MCU ACK
- Persistent serial connection
- Connected-state indicator
- Firmware selection and CRC display
- Update using the existing connection
- Background threads to keep the GUI responsive
"""

import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from serial.tools import list_ports

from app.firmware import FirmwareManager
from app.serial_port import SerialPort
from app.protocol_manager import ProtocolManager
from app.updater import FirmwareUpdater, UpdateResult


# ============================================================
# Configuration
# ============================================================

BAUDRATE_OPTIONS = [
    9600,
    19200,
    38400,
    57600,
    115200,
    230400,
    460800,
]

# Update this list according to the target MCU memory layout.
APP_ADDRESS_OPTIONS = [
    "0x08004000",
]

CHUNK_SIZE_OPTIONS = ["4", "8", "16"]

SYNC_RETRY_DELAY_MS = 250


# ============================================================
# Dark Engineering Theme
# ============================================================

DARK_STYLE = """
QMainWindow, QWidget#centralWidget {
    background-color: #10141C;
    color: #E6EDF7;
}

QWidget {
    color: #E6EDF7;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QFrame#card {
    background-color: #191F2B;
    border: 1px solid #2B3445;
    border-radius: 12px;
}

QLabel#pageTitle {
    font-size: 23pt;
    font-weight: 700;
    color: #F4F7FF;
}

QLabel#subtitle {
    font-size: 9pt;
    color: #8D9BB2;
}

QLabel#sectionTitle {
    font-size: 11pt;
    font-weight: 600;
    color: #C9D6EA;
}

QLabel#fieldLabel {
    color: #8D9BB2;
    font-size: 9pt;
}

QLabel#valueLabel {
    color: #F4F7FF;
    font-size: 10pt;
    font-weight: 600;
}

QLabel#statusDisconnected {
    color: #FF7777;
    font-weight: 700;
}

QLabel#statusConnecting {
    color: #FFC36B;
    font-weight: 700;
}

QLabel#statusConnected {
    color: #42D9A0;
    font-weight: 700;
}

QComboBox {
    background-color: #111722;
    border: 1px solid #344158;
    border-radius: 7px;
    padding: 9px;
    min-height: 18px;
}

QComboBox:hover {
    border: 1px solid #4C8DFF;
}

QComboBox:disabled {
    color: #647188;
    background-color: #171C26;
}

QComboBox QAbstractItemView {
    background-color: #191F2B;
    selection-background-color: #245BC4;
    border: 1px solid #344158;
}

QPushButton {
    background-color: #242D3D;
    border: 1px solid #35435A;
    border-radius: 7px;
    padding: 10px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #303C51;
    border-color: #4C8DFF;
}

QPushButton:disabled {
    background-color: #202633;
    color: #647188;
    border-color: #2B3445;
}

QPushButton#connectButton {
    background-color: #245BC4;
    color: white;
    border: none;
    padding: 12px 20px;
    font-weight: 700;
}

QPushButton#connectButton:hover {
    background-color: #3478F6;
}

QPushButton#connectingButton {
    background-color: #805B20;
    color: white;
    border: none;
    padding: 12px 20px;
}

QPushButton#connectedButton {
    background-color: #176B4B;
    color: white;
    border: none;
    padding: 12px 20px;
    font-weight: 700;
}

QPushButton#disconnectButton {
    background-color: #43252D;
    color: #FFAAAA;
    border: 1px solid #70404B;
}

QPushButton#updateButton {
    background-color: #3478F6;
    color: white;
    border: none;
    padding: 12px 22px;
    font-weight: 700;
}

QPushButton#updateButton:hover {
    background-color: #4C8DFF;
}

QProgressBar {
    background-color: #101722;
    border: 1px solid #303C50;
    border-radius: 6px;
    height: 16px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #3478F6;
    border-radius: 5px;
}

QTextEdit {
    background-color: #0C1119;
    color: #B9C9DF;
    border: 1px solid #2B3445;
    border-radius: 8px;
    padding: 10px;
    selection-background-color: #245BC4;
}

QScrollBar:vertical {
    background: #10141C;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #354158;
    border-radius: 4px;
    min-height: 25px;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
"""


# ============================================================
# Connection Worker
# ============================================================

class ConnectionWorker(QObject):
    """
    Opens the serial port and retries SYNC until the bootloader
    responds with a valid ACK.

    On successful connection, the serial port remains open.
    """

    connected = Signal(object, object)
    log = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, port: str, baudrate: int):
        super().__init__()

        self.port = port
        self.baudrate = baudrate

        self.cancel_event = threading.Event()

        self.serial_port = None
        self.protocol = None

    @Slot()
    def run(self):
        try:
            self.serial_port = SerialPort(
                port=self.port,
                baudrate=self.baudrate,
            )

            self.serial_port.open()

            self.protocol = ProtocolManager(
                serial_port=self.serial_port,
                response_timeout=2.0,
            )

            self.log.emit(
                f"Serial opened: {self.port} @ {self.baudrate}"
            )

            while not self.cancel_event.is_set():
                self.log.emit("TX: SYNC request")

                try:
                    # This method must wait for a valid ACK.
                    self.protocol.send_sync()

                    if self.cancel_event.is_set():
                        break

                    self.log.emit("RX: SYNC ACK received")

                    # Keep the serial port open after connection.
                    self.connected.emit(
                        self.serial_port,
                        self.protocol,
                    )
                    return

                except Exception as exc:
                    if self.cancel_event.is_set():
                        break

                    self.log.emit(
                        f"No valid SYNC response: {exc}"
                    )

                    # Prevent continuous high-speed retry loops.
                    self.cancel_event.wait(
                        SYNC_RETRY_DELAY_MS / 1000.0
                    )

            self._close_port()

        except Exception as exc:
            self._close_port()

            if not self.cancel_event.is_set():
                self.failed.emit(str(exc) or type(exc).__name__)

        finally:
            self.finished.emit()

    def cancel(self):
        self.cancel_event.set()

    def _close_port(self):
        if self.serial_port is not None:
            try:
                self.serial_port.close()
            except Exception:
                pass


# ============================================================
# Firmware Update Worker
# ============================================================

class UpdateWorker(QObject):
    """Runs firmware update on an existing serial connection."""

    progress = Signal(int, str)
    log = Signal(str)
    finished = Signal(object)

    def __init__(
        self,
        port: str,
        baudrate: int,
        app_address: int,
        chunk_size: int,
        firmware_path: Path,
        serial_port: SerialPort,
        protocol: ProtocolManager,
    ):
        super().__init__()

        self.port = port
        self.baudrate = baudrate
        self.app_address = app_address
        self.chunk_size = chunk_size
        self.firmware_path = firmware_path

        self.serial_port = serial_port
        self.protocol = protocol

    @Slot()
    def run(self):
        try:
            updater = FirmwareUpdater(
                port=self.port,
                baudrate=self.baudrate,
                app_start_address=self.app_address,
                chunk_size=self.chunk_size,
                progress_callback=self._on_progress,
                log_callback=self._on_log,
                serial_port=self.serial_port,
                protocol_manager=self.protocol,
            )

            updater.select_firmware(self.firmware_path)
            result = updater.run_update()

        except Exception as exc:
            result = UpdateResult(
                success=False,
                message=str(exc) or type(exc).__name__,
            )

        self.finished.emit(result)

    def _on_progress(self, percentage: int, message: str):
        self.progress.emit(percentage, message)

    def _on_log(self, message: str):
        self.log.emit(message)


# ============================================================
# Main Window
# ============================================================

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Universal Firmware Updater")
        self.resize(1080, 800)
        self.setMinimumSize(900, 700)

        self.firmware_path = None

        # Connection state
        self.connection_state = "disconnected"
        self.serial_connection = None
        self.protocol_connection = None

        # Thread references
        self.connection_thread = None
        self.connection_worker = None

        self.update_thread = None
        self.update_worker = None

        self.update_running = False
        self.closing = False

        self._build_ui()
        self.refresh_ports()
        self._set_connection_state("disconnected")

        self.append_log("Universal Firmware Updater initialized.")
        self.append_log("Select the target COM port, then Connect.")

    # ========================================================
    # UI Helpers
    # ========================================================

    def make_card(self, title: str):
        card = QFrame()
        card.setObjectName("card")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(14)

        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        return card, layout

    def make_field(self, label_text: str, widget: QWidget):
        container = QWidget()

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        label = QLabel(label_text.upper())
        label.setObjectName("fieldLabel")

        layout.addWidget(label)
        layout.addWidget(widget)

        return container

    # ========================================================
    # Build UI
    # ========================================================

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        # Header
        header = QHBoxLayout()

        title_column = QVBoxLayout()
        title_column.setSpacing(4)

        title = QLabel("Universal Firmware Updater")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "EMBEDDED SYSTEMS  /  STM32 BOOTLOADER  /  UART"
        )
        subtitle.setObjectName("subtitle")

        title_column.addWidget(title)
        title_column.addWidget(subtitle)

        header.addLayout(title_column)
        header.addStretch()

        self.header_status = QLabel("●  DISCONNECTED")
        self.header_status.setObjectName("statusDisconnected")

        header.addWidget(
            self.header_status,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        root.addLayout(header)

        # Connection settings
        connection_card, connection_layout = self.make_card(
            "01  /  Connection & Transfer Settings"
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(
            [str(rate) for rate in BAUDRATE_OPTIONS]
        )
        self.baud_combo.setCurrentText("115200")

        self.address_combo = QComboBox()
        self.address_combo.addItems(APP_ADDRESS_OPTIONS)

        self.chunk_combo = QComboBox()
        self.chunk_combo.addItems(CHUNK_SIZE_OPTIONS)
        self.chunk_combo.setCurrentText("16")

        self.refresh_button = QPushButton("↻  Refresh Ports")
        self.refresh_button.clicked.connect(self.refresh_ports)

        grid.addWidget(
            self.make_field("Serial Port", self.port_combo), 0, 0
        )
        grid.addWidget(
            self.make_field("Baud Rate", self.baud_combo), 0, 1
        )
        grid.addWidget(
            self.make_field(
                "Application Address", self.address_combo
            ), 1, 0
        )
        grid.addWidget(
            self.make_field(
                "Chunk Size (bytes)", self.chunk_combo
            ), 1, 1
        )
        grid.addWidget(self.refresh_button, 0, 2)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        connection_layout.addLayout(grid)

        # Connection controls
        connection_controls = QHBoxLayout()

        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("connectButton")
        self.connect_button.clicked.connect(self.connect_device)

        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setObjectName("disconnectButton")
        self.disconnect_button.clicked.connect(self.disconnect_device)
        self.disconnect_button.setEnabled(False)

        self.connection_detail = QLabel(
            "No MCU connection established"
        )
        self.connection_detail.setObjectName("subtitle")

        connection_controls.addWidget(self.connect_button)
        connection_controls.addWidget(self.disconnect_button)
        connection_controls.addWidget(self.connection_detail, 1)

        connection_layout.addLayout(connection_controls)
        root.addWidget(connection_card)

        # Firmware
        firmware_card, firmware_layout = self.make_card(
            "02  /  Firmware Image"
        )

        file_row = QHBoxLayout()
        file_row.setSpacing(12)

        file_column = QVBoxLayout()
        file_column.setSpacing(5)

        self.firmware_name = QLabel("No firmware selected")
        self.firmware_name.setObjectName("valueLabel")
        self.firmware_name.setWordWrap(True)

        self.firmware_details = QLabel(
            "Select a compiled .bin firmware file."
        )
        self.firmware_details.setObjectName("subtitle")
        self.firmware_details.setWordWrap(True)

        file_column.addWidget(self.firmware_name)
        file_column.addWidget(self.firmware_details)

        file_row.addLayout(file_column, 1)

        self.browse_button = QPushButton("Browse .bin  ↗")
        self.browse_button.setObjectName("browseButton")
        self.browse_button.clicked.connect(self.browse_firmware)

        file_row.addWidget(self.browse_button)
        firmware_layout.addLayout(file_row)

        root.addWidget(firmware_card)

        # Progress
        progress_card, progress_layout = self.make_card(
            "03  /  Update Progress"
        )

        progress_header = QHBoxLayout()

        self.progress_status = QLabel("Waiting for connection")
        self.progress_status.setObjectName("subtitle")

        self.progress_percent = QLabel("0%")
        self.progress_percent.setObjectName("valueLabel")

        progress_header.addWidget(self.progress_status)
        progress_header.addStretch()
        progress_header.addWidget(self.progress_percent)

        progress_layout.addLayout(progress_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")
        self.progress_bar.setMinimumHeight(18)

        progress_layout.addWidget(self.progress_bar)

        self.device_status = QLabel("Device: Not connected")
        self.device_status.setObjectName("subtitle")
        progress_layout.addWidget(self.device_status)

        root.addWidget(progress_card)

        # Log
        log_card, log_layout = self.make_card("04  /  Activity Log")

        log_header = QHBoxLayout()

        log_caption = QLabel("Connection events and update protocol")
        log_caption.setObjectName("subtitle")

        self.clear_button = QPushButton("Clear Log")
        self.clear_button.clicked.connect(self.clear_log)

        log_header.addWidget(log_caption)
        log_header.addStretch()
        log_header.addWidget(self.clear_button)

        log_layout.addLayout(log_header)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setMinimumHeight(140)
        self.log_view.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        log_layout.addWidget(self.log_view)
        root.addWidget(log_card, 1)

        # Footer / Update button
        footer = QHBoxLayout()

        self.footer_message = QLabel(
            "Connect to the MCU before starting an update"
        )
        self.footer_message.setObjectName("subtitle")

        self.update_button = QPushButton("▶  Update Firmware")
        self.update_button.setObjectName("updateButton")
        self.update_button.setEnabled(False)
        self.update_button.clicked.connect(self.start_update)

        footer.addWidget(self.footer_message)
        footer.addStretch()
        footer.addWidget(self.update_button)

        root.addLayout(footer)

    # ========================================================
    # Connection State
    # ========================================================

    def _set_connection_state(self, state: str):
        self.connection_state = state

        if state == "disconnected":
            self.connect_button.setText("Connect")
            self.connect_button.setObjectName("connectButton")
            self.header_status.setText("●  DISCONNECTED")
            self.header_status.setObjectName("statusDisconnected")

            self.connection_detail.setText(
                "No MCU connection established"
            )
            self.device_status.setText("Device: Not connected")

            self.connect_button.setEnabled(True)
            self.disconnect_button.setEnabled(False)
            self.update_button.setEnabled(False)

        elif state == "connecting":
            self.connect_button.setText("Connecting...")
            self.connect_button.setObjectName("connectingButton")
            self.header_status.setText("●  CONNECTING")
            self.header_status.setObjectName("statusConnecting")

            self.connection_detail.setText(
                "Waiting for bootloader SYNC response..."
            )
            self.device_status.setText(
                "Device: Waiting for MCU response"
            )

            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.update_button.setEnabled(False)

        elif state == "connected":
            self.connect_button.setText("Connected ✓")
            self.connect_button.setObjectName("connectedButton")
            self.header_status.setText("●  CONNECTED")
            self.header_status.setObjectName("statusConnected")

            self.connection_detail.setText(
                "Bootloader ACK received"
            )
            self.device_status.setText(
                "Device: Bootloader connected"
            )

            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.update_button.setEnabled(
                self.firmware_path is not None
                and not self.update_running
            )

        # Refresh stylesheet so the button's state color changes.
        self.connect_button.style().unpolish(self.connect_button)
        self.connect_button.style().polish(self.connect_button)
        self.header_status.style().unpolish(self.header_status)
        self.header_status.style().polish(self.header_status)

    # ========================================================
    # Logging
    # ========================================================

    @Slot(str)
    def append_log(self, message: str):
        self.log_view.append(message)

    @Slot()
    def clear_log(self):
        self.log_view.clear()

    # ========================================================
    # COM Ports
    # ========================================================

    @Slot()
    def refresh_ports(self):
        if self.connection_state != "disconnected":
            self.append_log(
                "Disconnect before changing the serial port."
            )
            return

        previous = self.port_combo.currentText()
        port_names = [
            port.device for port in list_ports.comports()
        ]

        self.port_combo.clear()
        self.port_combo.addItems(port_names)

        if previous in port_names:
            self.port_combo.setCurrentText(previous)

        if port_names:
            self.append_log(
                "Available ports: " + ", ".join(port_names)
            )
        else:
            self.append_log("WARNING: No serial ports detected.")

    # ========================================================
    # Connect / SYNC Retry
    # ========================================================

    @Slot()
    def connect_device(self):
        if self.connection_state != "disconnected":
            return

        port = self.port_combo.currentText()

        if not port:
            QMessageBox.warning(
                self,
                "No Serial Port",
                "Select a valid COM port first.",
            )
            return

        baudrate = int(self.baud_combo.currentText())

        self._set_connection_state("connecting")
        self.footer_message.setText(
            "Sending SYNC requests until the MCU responds..."
        )

        self.append_log("-" * 55)
        self.append_log(f"Connecting to {port} @ {baudrate}")
        self.append_log("SYNC retry started.")
        self.append_log("-" * 55)

        self.connection_thread = QThread(self)

        self.connection_worker = ConnectionWorker(
            port=port,
            baudrate=baudrate,
        )

        self.connection_worker.moveToThread(
            self.connection_thread
        )

        self.connection_thread.started.connect(
            self.connection_worker.run
        )

        self.connection_worker.log.connect(self.append_log)
        self.connection_worker.connected.connect(
            self.on_device_connected
        )
        self.connection_worker.failed.connect(
            self.on_connection_failed
        )

        self.connection_worker.finished.connect(
            self.connection_thread.quit
        )
        self.connection_thread.finished.connect(
            self.on_connection_thread_finished
        )

        self.connection_thread.start()

    @Slot(object, object)
    def on_device_connected(
        self,
        serial_port: SerialPort,
        protocol: ProtocolManager,
    ):
        self.serial_connection = serial_port
        self.protocol_connection = protocol

        self._set_connection_state("connected")

        self.footer_message.setText(
            "MCU connected. Firmware update is available."
        )

        self.append_log("CONNECTION SUCCESS: MCU ACK received.")
        self.append_log("Serial connection remains open.")

    @Slot(str)
    def on_connection_failed(self, message: str):
        self.serial_connection = None
        self.protocol_connection = None

        self._set_connection_state("disconnected")

        self.footer_message.setText(
            "Connection failed. Check the port and target MCU."
        )

        self.append_log("CONNECTION ERROR: " + message)

        QMessageBox.warning(
            self,
            "Connection Failed",
            message,
        )

    @Slot()
    def on_connection_thread_finished(self):
        self.connection_worker = None
        self.connection_thread = None

        # A cancelled connection attempt should return to idle.
        if (
            self.connection_state == "connecting"
            and self.serial_connection is None
        ):
            self._set_connection_state("disconnected")

    # ========================================================
    # Disconnect
    # ========================================================

    @Slot()
    def disconnect_device(self):
        if self.update_running:
            QMessageBox.information(
                self,
                "Update In Progress",
                "Disconnect is disabled while firmware update is running.",
            )
            return

        if self.connection_state == "connecting":
            worker = self.connection_worker

            if worker is not None:
                worker.cancel()

            self.append_log("Cancelling connection attempt...")
            self.disconnect_button.setEnabled(False)
            return

        if self.connection_state == "connected":
            try:
                if self.serial_connection is not None:
                    self.serial_connection.close()
            except Exception as exc:
                self.append_log(
                    f"Error while closing serial port: {exc}"
                )

        self.serial_connection = None
        self.protocol_connection = None

        self._set_connection_state("disconnected")
        self.footer_message.setText(
            "Disconnected. Connect to the MCU to continue."
        )
        self.append_log("Device disconnected.")

    # ========================================================
    # Firmware Selection
    # ========================================================

    @Slot()
    def browse_firmware(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Firmware Binary",
            "",
            "Firmware Binary (*.bin)",
        )

        if not file_name:
            return

        try:
            firmware = FirmwareManager()
            firmware.load(file_name)

            self.firmware_path = Path(file_name)

            self.firmware_name.setText(
                self.firmware_path.name
            )
            self.firmware_details.setText(
                f"Size: {firmware.size:,} bytes    |    "
                f"CRC16-CCITT-FALSE: 0x{firmware.crc:04X}"
            )

            self.progress_bar.setValue(0)
            self.progress_percent.setText("0%")
            self.progress_status.setText("Firmware loaded")

            self.append_log(
                f"Firmware loaded: {self.firmware_path}"
            )
            self.append_log(
                f"Firmware size: {firmware.size} bytes"
            )
            self.append_log(
                f"Firmware CRC16: 0x{firmware.crc:04X}"
            )

            # Update is enabled only if the MCU is connected.
            self.update_button.setEnabled(
                self.connection_state == "connected"
                and not self.update_running
            )

        except Exception as exc:
            self.firmware_path = None
            self.firmware_name.setText("No firmware selected")
            self.firmware_details.setText(
                "Could not load firmware."
            )
            self.update_button.setEnabled(False)

            QMessageBox.critical(
                self,
                "Firmware Error",
                str(exc),
            )

    # ========================================================
    # Firmware Update
    # ========================================================

    @Slot()
    def start_update(self):
        if self.update_running:
            return

        if self.connection_state != "connected":
            QMessageBox.warning(
                self,
                "Not Connected",
                "Connect to the MCU before updating firmware.",
            )
            return

        if (
            self.serial_connection is None
            or self.protocol_connection is None
        ):
            QMessageBox.warning(
                self,
                "Connection Error",
                "The serial connection is not available. Reconnect.",
            )
            self._set_connection_state("disconnected")
            return

        if self.firmware_path is None:
            QMessageBox.warning(
                self,
                "No Firmware",
                "Select a .bin firmware file first.",
            )
            return

        port = self.port_combo.currentText()
        baudrate = int(self.baud_combo.currentText())
        app_address = int(self.address_combo.currentText(), 16)
        chunk_size = int(self.chunk_combo.currentText())

        self.update_running = True
        self.update_button.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.refresh_button.setEnabled(False)

        self.progress_bar.setValue(0)
        self.progress_percent.setText("0%")
        self.progress_status.setText("Starting firmware update...")
        self.footer_message.setText("Firmware update in progress")

        self.append_log("-" * 55)
        self.append_log("Firmware update started.")
        self.append_log(f"Port: {port} @ {baudrate}")
        self.append_log(
            f"Application address: 0x{app_address:08X}"
        )
        self.append_log(f"Chunk size: {chunk_size} bytes")
        self.append_log("-" * 55)

        self.update_thread = QThread(self)

        self.update_worker = UpdateWorker(
            port=port,
            baudrate=baudrate,
            app_address=app_address,
            chunk_size=chunk_size,
            firmware_path=self.firmware_path,
            serial_port=self.serial_connection,
            protocol=self.protocol_connection,
        )

        self.update_worker.moveToThread(self.update_thread)

        self.update_thread.started.connect(self.update_worker.run)

        self.update_worker.progress.connect(self.on_progress)
        self.update_worker.log.connect(self.append_log)
        self.update_worker.finished.connect(
            self.on_update_finished
        )

        self.update_worker.finished.connect(
            self.update_thread.quit
        )
        self.update_thread.finished.connect(
            self.on_update_thread_finished
        )

        self.update_thread.start()

    # ========================================================
    # Update Progress
    # ========================================================

    @Slot(int, str)
    def on_progress(self, percentage: int, message: str):
        self.progress_bar.setValue(percentage)
        self.progress_percent.setText(f"{percentage}%")
        self.progress_status.setText(message)

        if "Synchronizing" in message:
            self.device_status.setText(
                "Device: Synchronizing..."
            )
        elif "Requesting device ID" in message:
            self.device_status.setText(
                "Device: Reading device ID..."
            )
        elif "Transferred" in message:
            self.device_status.setText(
                "Device: Transferring firmware..."
            )
        elif "completed" in message.lower():
            self.device_status.setText(
                "Device: Update completed"
            )

    @Slot(object)
    def on_update_finished(self, result: UpdateResult):
        self.update_running = False

        self.browse_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.disconnect_button.setEnabled(True)

        # The persistent serial connection should remain open.
        # Do not mark the device disconnected just because an
        # update failed; allow retry or manual disconnect.
        self._set_connection_state("connected")

        if result.success:
            self.progress_bar.setValue(100)
            self.progress_percent.setText("100%")
            self.progress_status.setText(
                "Firmware update completed"
            )
            self.device_status.setText(
                f"Device ID: {result.device_id or 'Connected'}"
            )
            self.footer_message.setText(
                "Firmware update successful. MCU remains connected."
            )

            self.append_log("UPDATE SUCCESS: " + result.message)

            QMessageBox.information(
                self,
                "Update Successful",
                result.message,
            )

        else:
            self.progress_status.setText(
                "Firmware update failed"
            )
            self.footer_message.setText(
                "Update failed. Check the log before retrying."
            )

            self.append_log("UPDATE FAILED: " + result.message)

            QMessageBox.critical(
                self,
                "Update Failed",
                result.message,
            )

    @Slot()
    def on_update_thread_finished(self):
        self.update_worker = None
        self.update_thread = None

    # ========================================================
    # Application Shutdown
    # ========================================================

    def closeEvent(self, event):
        if self.update_running:
            QMessageBox.warning(
                self,
                "Update In Progress",
                "Wait for the firmware update to finish before closing.",
            )
            event.ignore()
            return

        if self.connection_state == "connecting":
            worker = self.connection_worker
            thread = self.connection_thread

            if worker is not None:
                worker.cancel()

            if thread is not None:
                thread.quit()
                thread.wait(2500)

        if self.serial_connection is not None:
            try:
                self.serial_connection.close()
            except Exception:
                pass

        event.accept()


# ============================================================
# Application Entry Point
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLE)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()