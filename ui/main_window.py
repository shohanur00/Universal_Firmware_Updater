
"""
Universal Firmware Updater
Main Window - Midnight Engineer Theme

Features:
- Serial Connect / Disconnect
- Complete bootloader handshake and device ID verification
- Firmware selection and update
- Progress reporting and activity log
- Firmware erase command
- Reuse of GUI-owned serial connection
"""

import sys
from pathlib import Path
from PySide6.QtGui import QIcon

# Allow direct execution:
# python ui/main_window.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QLineEdit,
    QFileDialog,
    QProgressBar,
    QPlainTextEdit,
    QGroupBox,
    QMessageBox,
    QFrame,
    QSizePolicy,
)

from app.serial_port import SerialPort
from app.protocol_manager import ProtocolManager
from app.updater import FirmwareUpdater, UpdateResult


# ============================================================
# Configuration
# ============================================================

DEFAULT_BAUDRATE = 115200
DEFAULT_APP_ADDRESS = "0x08004000"
DEFAULT_CHUNK_SIZE = 16
CONNECTION_ATTEMPTS = 30


# ============================================================
# Midnight Engineer Theme
# ============================================================

APP_STYLE = """
QMainWindow, QWidget {
    background-color: #171A19;
    color: #E6EAE7;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QGroupBox {
    background-color: #1E2321;
    border: 1px solid #343C37;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 10px 10px 10px;
    font-weight: 600;
    color: #DCE4DE;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #8DBB9A;
}

QLabel {
    background: transparent;
}

QLineEdit, QComboBox {
    background-color: #111412;
    color: #E6EAE7;
    border: 1px solid #3B4540;
    border-radius: 5px;
    padding: 7px 9px;
    min-height: 20px;
    selection-background-color: #426C50;
}

QComboBox {
    padding-right: 24px;
}

QComboBox QAbstractItemView {
    background-color: #202622;
    color: #E6EAE7;
    selection-background-color: #355940;
    border: 1px solid #46534A;
    outline: 0;
}

QPushButton {
    background-color: #29312C;
    color: #E6EAE7;
    border: 1px solid #455148;
    border-radius: 6px;
    padding: 8px 12px;
    min-height: 20px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #35443A;
    border-color: #71977A;
}

QPushButton:pressed {
    background-color: #24372A;
}

QPushButton:disabled {
    background-color: #242825;
    color: #737B75;
    border-color: #303631;
}

QPushButton#primaryButton {
    background-color: #416D4D;
    color: #FFFFFF;
    border: 1px solid #588665;
}

QPushButton#primaryButton:hover {
    background-color: #4D805B;
}

QPushButton#dangerButton {
    background-color: #653A35;
    border: 1px solid #875047;
    color: #FFFFFF;
}

QPushButton#dangerButton:hover {
    background-color: #79463F;
}

QPlainTextEdit {
    background-color: #101311;
    color: #BBD4C1;
    border: 1px solid #343C37;
    border-radius: 6px;
    padding: 8px;
    selection-background-color: #355940;
    font-family: Consolas, "Courier New";
    font-size: 9pt;
}

QProgressBar {
    background-color: #101311;
    color: #FFFFFF;
    border: 1px solid #39443C;
    border-radius: 5px;
    text-align: center;
    min-height: 22px;
    max-height: 22px;
}

QProgressBar::chunk {
    background-color: #527E5C;
    border-radius: 4px;
}

QFrame#separator {
    background-color: #343C37;
    max-height: 1px;
}
"""


# ============================================================
# Connection Worker
# ============================================================

class ConnectionWorker(QThread):
    log = Signal(str)
    connected = Signal(object, object, object)
    failed = Signal(str)

    def __init__(self, port_name, baudrate, parent=None):
        super().__init__(parent)

        self.port_name = port_name
        self.baudrate = baudrate

        self.serial_port = None
        self.protocol = None

    def run(self):
        try:
            self.log.emit(
                f"Opening {self.port_name} "
                f"at {self.baudrate} baud..."
            )

            self.serial_port = SerialPort(
                port=self.port_name,
                baudrate=self.baudrate,
            )

            self.serial_port.open()

            self.protocol = ProtocolManager(
                serial_port=self.serial_port,
                response_timeout=10.0,
            )

            self.log.emit("Serial port opened.")
            self.log.emit(
                "Starting bootloader handshake..."
            )

            last_error = None
            device_id = None

            for attempt in range(1, CONNECTION_ATTEMPTS + 1):
                try:
                    self.log.emit(
                        f"Handshake attempt "
                        f"{attempt}/{CONNECTION_ATTEMPTS}"
                    )

                    # Complete handshake:
                    # SYNC -> ACK
                    # DEVICE_ID_REQ -> DEVICE_ID_RES
                    # Verify UID -> DEVICE_ID_CONFIRM -> ACK
                    device_id = (
                        self.protocol.connect_and_verify()
                    )

                    # Do not report connection success unless
                    # the ProtocolManager confirms verification.
                    if not self.protocol.is_device_verified:
                        raise RuntimeError(
                            "Device verification was not completed."
                        )

                    break

                except Exception as exc:
                    last_error = exc

                    self.log.emit(
                        f"Handshake attempt {attempt} failed: {exc}"
                    )

                    device_id = None

            if device_id is None:
                raise RuntimeError(
                    "Bootloader handshake failed after "
                    f"{CONNECTION_ATTEMPTS} attempts. "
                    f"Last error: {last_error}"
                )

            self.log.emit(
                f"Device ID received: {device_id.hex().upper()}"
            )
            self.log.emit(
                "Device ID handshake completed successfully."
            )

            self.connected.emit(
                self.serial_port,
                self.protocol,
                device_id,
            )

        except Exception as exc:
            if self.serial_port is not None:
                try:
                    self.serial_port.close()
                except Exception:
                    pass

            self.failed.emit(str(exc))


# ============================================================
# Firmware Update Worker
# ============================================================

class UpdateWorker(QThread):
    progress = Signal(int, str)
    log = Signal(str)
    update_completed = Signal(object)

    def __init__(
        self,
        port,
        baudrate,
        app_start_address,
        chunk_size,
        firmware_path,
        serial_port,
        protocol_manager,
        parent=None,
    ):
        super().__init__(parent)

        self.port = port
        self.baudrate = baudrate
        self.app_start_address = app_start_address
        self.chunk_size = chunk_size
        self.firmware_path = firmware_path
        self.serial_port = serial_port
        self.protocol_manager = protocol_manager

    def run(self):
        try:
            updater = FirmwareUpdater(
                port=self.port,
                baudrate=self.baudrate,
                app_start_address=self.app_start_address,
                chunk_size=self.chunk_size,
                progress_callback=self.progress.emit,
                log_callback=self.log.emit,
                serial_port=self.serial_port,
                protocol_manager=self.protocol_manager,
            )

            self.log.emit(
                f"Loading firmware: {self.firmware_path}"
            )

            updater.select_firmware(self.firmware_path)

            result = updater.run_update()

            self.update_completed.emit(result)

        except Exception as exc:
            self.log.emit(f"UPDATE ERROR: {exc}")

            self.update_completed.emit(
                UpdateResult(
                    success=False,
                    message=str(exc),
                )
            )


# ============================================================
# Erase Worker
# ============================================================

class EraseWorker(QThread):
    log = Signal(str)
    erase_completed = Signal(bool, str)

    def __init__(self, protocol_manager, parent=None):
        super().__init__(parent)
        self.protocol_manager = protocol_manager

    def run(self):
        try:
            self.log.emit(
                "Sending firmware erase command..."
            )

            self.protocol_manager.erase_firmware()

            self.log.emit(
                "Firmware erase command acknowledged."
            )

            self.erase_completed.emit(
                True,
                "Firmware erase completed successfully.",
            )

        except Exception as exc:
            self.log.emit(f"ERASE ERROR: {exc}")
            self.erase_completed.emit(False, str(exc))


# ============================================================
# Main Window
# ============================================================

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Universal Firmware Updater")
        self.resize(1050, 760)
        self.setMinimumSize(760, 600)
        self.setStyleSheet(APP_STYLE)

        self.serial_port = None
        self.protocol = None
        self.device_id = None

        self.connection_worker = None
        self.update_worker = None
        self.erase_worker = None

        self.firmware_path = ""

        self._build_ui()
        self._update_controls()

    # ========================================================
    # UI Construction
    # ========================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        # Header
        header = QHBoxLayout()

        title_layout = QVBoxLayout()
        title_layout.setSpacing(3)

        title = QLabel("UNIVERSAL FIRMWARE UPDATER")
        title.setFont(
            QFont("Segoe UI", 17, QFont.Weight.Bold)
        )
        title.setStyleSheet("color: #E8EEE9;")

        subtitle = QLabel(
            "STM32 Bootloader  •  UART Firmware Programming"
        )
        subtitle.setStyleSheet(
            "color: #8C9990; font-size: 9pt;"
        )

        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        header.addLayout(title_layout)
        header.addStretch()

        self.status_label = QLabel("● DISCONNECTED")
        self.status_label.setStyleSheet(
            "color: #D58A7D; font-weight: bold;"
        )

        header.addWidget(self.status_label)
        root.addLayout(header)

        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(separator)

        # Main panels
        top_layout = QHBoxLayout()
        top_layout.setSpacing(14)

        top_layout.addWidget(
            self._build_connection_group(),
            1,
        )
        top_layout.addWidget(
            self._build_firmware_group(),
            1,
        )

        root.addLayout(top_layout)

        # Progress
        progress_group = QGroupBox("Update Progress")
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setSpacing(8)

        self.progress_status = QLabel("Ready.")
        self.progress_status.setStyleSheet(
            "color: #B6C5BA;"
        )

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

        progress_layout.addWidget(self.progress_status)
        progress_layout.addWidget(self.progress_bar)

        root.addWidget(progress_group)

        # Activity log
        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(log_group)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText(
            "Connection and firmware update messages "
            "will appear here..."
        )
        self.log_view.setMinimumHeight(170)
        self.log_view.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        log_buttons = QHBoxLayout()

        self.clear_log_button = QPushButton("Clear Log")
        self.clear_log_button.setFixedWidth(105)
        self.clear_log_button.clicked.connect(
            self.log_view.clear
        )

        log_buttons.addStretch()
        log_buttons.addWidget(self.clear_log_button)

        log_layout.addWidget(self.log_view)
        log_layout.addLayout(log_buttons)

        root.addWidget(log_group, 1)

        self._log(
            "Universal Firmware Updater initialized."
        )

    def _build_connection_group(self):
        group = QGroupBox("Connection")
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(12)

        layout.addWidget(QLabel("COM Port"), 0, 0)

        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.addItems(
            [f"COM{i}" for i in range(1, 21)]
        )
        self.port_combo.setCurrentText("COM7")
        self.port_combo.setMinimumWidth(110)

        layout.addWidget(self.port_combo, 0, 1)

        layout.addWidget(QLabel("Baud Rate"), 1, 0)

        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(
            [
                "9600",
                "19200",
                "38400",
                "57600",
                "115200",
                "230400",
            ]
        )
        self.baudrate_combo.setCurrentText(
            str(DEFAULT_BAUDRATE)
        )

        layout.addWidget(self.baudrate_combo, 1, 1)

        button_row = QHBoxLayout()

        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.setFixedWidth(115)
        self.connect_button.clicked.connect(
            self._connect
        )

        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setFixedWidth(115)
        self.disconnect_button.clicked.connect(
            self._disconnect
        )

        button_row.addWidget(self.connect_button)
        button_row.addWidget(self.disconnect_button)
        button_row.addStretch()

        layout.addLayout(button_row, 2, 0, 1, 2)

        self.connection_info = QLabel(
            "Select a COM port and connect to the bootloader."
        )
        self.connection_info.setWordWrap(True)
        self.connection_info.setStyleSheet(
            "color: #8C9990; font-size: 9pt;"
        )

        layout.addWidget(
            self.connection_info,
            3, 0, 1, 2,
        )

        return group

    def _build_firmware_group(self):
        group = QGroupBox("Firmware Configuration")
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

        layout.addWidget(
            QLabel("Firmware File"),
            0, 0, 1, 2,
        )

        file_row = QHBoxLayout()

        self.firmware_path_edit = QLineEdit()
        self.firmware_path_edit.setReadOnly(True)
        self.firmware_path_edit.setPlaceholderText(
            "Select a .bin firmware file..."
        )

        self.browse_button = QPushButton("Browse")
        self.browse_button.setFixedWidth(90)
        self.browse_button.clicked.connect(
            self._browse_firmware
        )

        file_row.addWidget(self.firmware_path_edit, 1)
        file_row.addWidget(self.browse_button)

        layout.addLayout(file_row, 1, 0, 1, 2)

        layout.addWidget(
            QLabel("Application Address"),
            2, 0,
        )

        self.address_edit = QLineEdit(
            DEFAULT_APP_ADDRESS
        )
        self.address_edit.setToolTip(
            "Target application's flash start address, "
            "e.g. 0x08004000"
        )

        layout.addWidget(self.address_edit, 2, 1)

        layout.addWidget(QLabel("Chunk Size"), 3, 0)

        self.chunk_combo = QComboBox()
        self.chunk_combo.addItems(["4", "8", "16"])
        self.chunk_combo.setCurrentText(
            str(DEFAULT_CHUNK_SIZE)
        )

        layout.addWidget(self.chunk_combo, 3, 1)

        action_row = QHBoxLayout()

        self.update_button = QPushButton(
            "Update Firmware"
        )
        self.update_button.setObjectName("primaryButton")
        self.update_button.setFixedWidth(145)
        self.update_button.clicked.connect(
            self._start_update
        )

        self.erase_button = QPushButton("Erase Firmware")
        self.erase_button.setObjectName("dangerButton")
        self.erase_button.setFixedWidth(130)
        self.erase_button.clicked.connect(
            self._erase_firmware
        )

        action_row.addWidget(self.update_button)
        action_row.addWidget(self.erase_button)
        action_row.addStretch()

        layout.addLayout(action_row, 4, 0, 1, 2)

        note = QLabel(
            "Check the target MCU's flash layout "
            "before programming."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "color: #8C9990; font-size: 9pt;"
        )

        layout.addWidget(note, 5, 0, 1, 2)

        return group

    # ========================================================
    # Logging / Status
    # ========================================================

    def _log(self, message):
        self.log_view.appendPlainText(str(message))

    def _set_status(self, connected):
        if connected:
            self.status_label.setText("● CONNECTED")
            self.status_label.setStyleSheet(
                "color: #8BC49A; font-weight: bold;"
            )
        else:
            self.status_label.setText("● DISCONNECTED")
            self.status_label.setStyleSheet(
                "color: #D58A7D; font-weight: bold;"
            )

    def _is_device_verified(self):
        """Return True only for an open, verified session."""
        if self.serial_port is None or self.protocol is None:
            return False

        if not self.serial_port.is_open:
            return False

        return bool(
            getattr(
                self.protocol,
                "is_device_verified",
                False,
            )
        )

    def _update_controls(self):
        port_open = (
            self.serial_port is not None
            and self.protocol is not None
            and self.serial_port.is_open
        )

        # Firmware actions require a verified handshake.
        verified = (
            port_open
            and self._is_device_verified()
        )

        worker_busy = self._busy()

        self.connect_button.setEnabled(
            not worker_busy and not port_open
        )

        self.disconnect_button.setEnabled(
            not worker_busy and port_open
        )

        self.update_button.setEnabled(
            not worker_busy and verified
        )

        self.erase_button.setEnabled(
            not worker_busy and verified
        )

        self.browse_button.setEnabled(not worker_busy)

        self.port_combo.setEnabled(
            not worker_busy and not port_open
        )

        self.baudrate_combo.setEnabled(
            not worker_busy and not port_open
        )

    # ========================================================
    # Connection
    # ========================================================

    def _connect(self):
        if self.connection_worker is not None:
            if self.connection_worker.isRunning():
                return

        port = self.port_combo.currentText().strip()

        if not port:
            QMessageBox.warning(
                self,
                "Missing COM Port",
                "Please select a serial port.",
            )
            return

        try:
            baudrate = int(
                self.baudrate_combo.currentText()
            )
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Baud Rate",
                "Please select a valid baud rate.",
            )
            return

        self._log(f"Connecting to {port}...")
        self.connection_info.setText(
            "Opening serial port and verifying device..."
        )

        self._update_controls()

        self.connection_worker = ConnectionWorker(
            port_name=port,
            baudrate=baudrate,
            parent=self,
        )

        self.connection_worker.log.connect(self._log)

        self.connection_worker.connected.connect(
            self._on_connected
        )

        self.connection_worker.failed.connect(
            self._on_connection_failed
        )

        self.connection_worker.finished.connect(
            self._on_connection_worker_finished
        )

        self.connection_worker.start()

    def _on_connected(
        self,
        serial_port,
        protocol,
        device_id,
    ):
        self.serial_port = serial_port
        self.protocol = protocol
        self.device_id = bytes(device_id)

        if not self._is_device_verified():
            self._log(
                "CONNECTION ERROR: Device verification "
                "was not active after handshake."
            )

            try:
                self.serial_port.close()
            except Exception:
                pass

            self.serial_port = None
            self.protocol = None
            self.device_id = None

            self._set_status(False)
            self.connection_info.setText(
                "Device verification failed."
            )
            self._update_controls()
            return

        port = self.port_combo.currentText().strip()
        baudrate = self.baudrate_combo.currentText()

        self._set_status(True)

        self.connection_info.setText(
            f"Verified device on {port} at {baudrate} baud."
        )

        self._log("Connection established.")
        self._log(
            f"Verified device UID: "
            f"{self.device_id.hex().upper()}"
        )

        self._update_controls()

    def _on_connection_failed(self, message):
        self.serial_port = None
        self.protocol = None
        self.device_id = None

        self._set_status(False)
        self.connection_info.setText(
            "Connection or device verification failed."
        )

        self._log(
            f"CONNECTION ERROR: {message}"
        )

    def _on_connection_worker_finished(self):
        self.connection_worker = None
        self._update_controls()

    def _disconnect(self):
        if self._busy():
            return

        if self.serial_port is not None:
            try:
                self.serial_port.close()
                self._log("Serial port closed.")
            except Exception as exc:
                self._log(
                    f"Disconnect warning: {exc}"
                )

        self.serial_port = None
        self.protocol = None
        self.device_id = None

        self._set_status(False)

        self.connection_info.setText("Disconnected.")
        self.progress_status.setText("Ready.")

        self._update_controls()

    # ========================================================
    # Firmware Selection
    # ========================================================

    def _browse_firmware(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Firmware",
            "",
            "Firmware Binary (*.bin);;All Files (*)",
        )

        if not file_path:
            return

        self.firmware_path = file_path
        self.firmware_path_edit.setText(file_path)

        self._log(
            f"Selected firmware: {file_path}"
        )

    # ========================================================
    # Firmware Update
    # ========================================================

    def _start_update(self):
        if self._busy():
            return

        if not self._is_device_verified():
            QMessageBox.warning(
                self,
                "Device Not Verified",
                (
                    "Connect to the bootloader and complete "
                    "device verification first."
                ),
            )
            return

        if not self.firmware_path:
            QMessageBox.warning(
                self,
                "Firmware Missing",
                "Please select a .bin firmware file.",
            )
            return

        try:
            address = int(
                self.address_edit.text().strip(),
                0,
            )
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Address",
                "Enter a valid address, e.g. 0x08004000.",
            )
            return

        chunk_size = int(
            self.chunk_combo.currentText()
        )

        port = self.port_combo.currentText().strip()
        baudrate = int(
            self.baudrate_combo.currentText()
        )

        confirm = QMessageBox.question(
            self,
            "Start Firmware Update",
            (
                "Start firmware update?\n\n"
                f"Port: {port}\n"
                f"Baud rate: {baudrate}\n"
                f"Application address: 0x{address:08X}\n"
                f"Chunk size: {chunk_size} bytes\n\n"
                "Do not disconnect power during programming."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        self.progress_bar.setValue(0)
        self.progress_status.setText(
            "Starting firmware update..."
        )

        self._log("========================================")
        self._log("Starting firmware update...")

        self._update_controls()

        self.update_worker = UpdateWorker(
            port=port,
            baudrate=baudrate,
            app_start_address=address,
            chunk_size=chunk_size,
            firmware_path=self.firmware_path,
            serial_port=self.serial_port,
            protocol_manager=self.protocol,
            parent=self,
        )

        self.update_worker.progress.connect(
            self._on_update_progress
        )

        self.update_worker.log.connect(self._log)

        self.update_worker.update_completed.connect(
            self._on_update_completed
        )

        self.update_worker.finished.connect(
            self._on_update_worker_finished
        )

        self.update_worker.start()

    def _on_update_progress(
        self,
        percentage,
        message,
    ):
        self.progress_bar.setValue(percentage)
        self.progress_status.setText(message)

    def _on_update_completed(self, result):
        if result.success:
            self.progress_bar.setValue(100)

            self.progress_status.setText(
                "Firmware update completed successfully."
            )

            self._log("UPDATE SUCCESS")

            QMessageBox.information(
                self,
                "Update Complete",
                result.message,
            )

        else:
            self.progress_status.setText(
                "Firmware update failed."
            )

            self._log(
                f"UPDATE FAILED: {result.message}"
            )

            QMessageBox.critical(
                self,
                "Update Failed",
                result.message,
            )

    def _on_update_worker_finished(self):
        self.update_worker = None
        self._update_controls()

    # ========================================================
    # Erase Firmware
    # ========================================================

    def _erase_firmware(self):
        if self._busy():
            return

        if not self._is_device_verified():
            QMessageBox.warning(
                self,
                "Device Not Verified",
                (
                    "Connect to the bootloader and complete "
                    "device verification before erasing firmware."
                ),
            )
            return

        confirm = QMessageBox.warning(
            self,
            "Confirm Firmware Erase",
            (
                "Are you sure you want to erase firmware?\n\n"
                "This command must be supported by your STM32 "
                "bootloader. The operation may make the "
                "application unavailable until new firmware "
                "is programmed."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._log("Starting firmware erase...")
        self.progress_status.setText(
            "Erasing firmware..."
        )

        self._update_controls()

        self.erase_worker = EraseWorker(
            protocol_manager=self.protocol,
            parent=self,
        )

        self.erase_worker.log.connect(self._log)

        self.erase_worker.erase_completed.connect(
            self._on_erase_completed
        )

        self.erase_worker.finished.connect(
            self._on_erase_worker_finished
        )

        self.erase_worker.start()

    def _on_erase_completed(self, success, message):
        if success:
            self.progress_status.setText(
                "Erase completed."
            )

            self._log(message)

            QMessageBox.information(
                self,
                "Erase Complete",
                message,
            )

        else:
            self.progress_status.setText(
                "Erase failed."
            )

            self._log(
                f"ERASE FAILED: {message}"
            )

            QMessageBox.critical(
                self,
                "Erase Failed",
                message,
            )

    def _on_erase_worker_finished(self):
        self.erase_worker = None
        self._update_controls()

    # ========================================================
    # Helpers / Shutdown
    # ========================================================

    def _busy(self):
        return any(
            worker is not None and worker.isRunning()
            for worker in (
                self.connection_worker,
                self.update_worker,
                self.erase_worker,
            )
        )

    def closeEvent(self, event):
        if self._busy():
            QMessageBox.warning(
                self,
                "Operation in Progress",
                (
                    "Wait for the current operation to finish "
                    "before closing."
                ),
            )
            event.ignore()
            return

        if self.serial_port is not None:
            try:
                self.serial_port.close()
            except Exception:
                pass

        event.accept()


# ============================================================
# Application Entry Point
# ============================================================


def main():
    app = QApplication.instance()

    if app is None:
        app = QApplication(sys.argv)

    project_root = Path(__file__).resolve().parent.parent
    icon_path = project_root / "assets" / "app_icon.ico"

    app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    # Keep a reference to the window for the app's lifetime.
    app._main_window = window

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

