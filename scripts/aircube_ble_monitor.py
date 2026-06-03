"""
AirCube BLE Monitor — base app for discovering AirCubes over Bluetooth.

Discovers multiple AirCubes via BTHome v2 BLE advertisements (firmware 1.6.0+),
lets you name and persist known cubes, shows live readings with AQI and LED-matching
color computed from TVOC, and plots per-cube history.

Run:
    pip install -r requirements.txt
    python aircube_ble_monitor.py
"""

from __future__ import annotations

__version__ = "0.1.0"
__app_name__ = "AirCube BLE Monitor"

import asyncio
import collections
import json
import os
import sys
import time
from datetime import datetime

try:
    from bleak import BleakScanner
except ImportError:
    print(
        "bleak is required for BLE scanning.\n"
        "Install dependencies: pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from aircube_ble_core import (
    aqi_from_tvoc,
    aqi_rating,
    aqi_to_hex,
    get_bthome_payload,
    is_aircube_advertisement,
    parse_bthome,
)

KNOWN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "known_aircubes.json")
STALE_SECONDS = 30
HISTORY_MAX_POINTS = 600


# ---------------------------------------------------------------------------
# BLE scanner thread
# ---------------------------------------------------------------------------


class BLEScannerThread(QThread):
    """Background thread running a bleak BleakScanner asyncio loop."""

    device_seen = pyqtSignal(str, dict)
    error_occurred = pyqtSignal(str)
    scan_state = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._running = False

    def run(self):
        self._running = True
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._scan())
        except Exception as exc:
            self.error_occurred.emit(str(exc))
        finally:
            loop.close()

    async def _scan(self):
        scanner = BleakScanner(detection_callback=self._on_adv)
        await scanner.start()
        self.scan_state.emit(True)
        try:
            while self._running:
                await asyncio.sleep(0.5)
        finally:
            await scanner.stop()
            self.scan_state.emit(False)

    def _on_adv(self, device, adv):
        # Called on the asyncio loop thread; Qt signals are thread-safe.
        if not is_aircube_advertisement(adv):
            return
        payload = get_bthome_payload(adv)
        values = parse_bthome(payload) if payload else {}
        values["rssi"] = adv.rssi
        values["name"] = adv.local_name or ""
        # device.address is MAC on Windows/Linux; a system UUID on macOS (stable per host).
        self.device_seen.emit(device.address, values)

    def stop(self):
        self._running = False
        self.wait(3000)


# ---------------------------------------------------------------------------
# Cube state and persistence
# ---------------------------------------------------------------------------


class CubeState:
    """Live readings and bounded history for one AirCube."""

    def __init__(self, address: str, name: str | None = None, known: bool = False):
        self.address = address
        self.name = name
        self.known = known
        self.last_seen: float | None = None
        self.rssi: int | None = None
        self.temperature_c: float | None = None
        self.humidity: float | None = None
        self.eco2: int | None = None
        self.etvoc: int | None = None
        self.aqi: int | None = None
        self.t0: float | None = None
        self.history_t: collections.deque = collections.deque(maxlen=HISTORY_MAX_POINTS)
        self.history_temp: collections.deque = collections.deque(maxlen=HISTORY_MAX_POINTS)
        self.history_hum: collections.deque = collections.deque(maxlen=HISTORY_MAX_POINTS)
        self.history_aqi: collections.deque = collections.deque(maxlen=HISTORY_MAX_POINTS)
        self.history_eco2: collections.deque = collections.deque(maxlen=HISTORY_MAX_POINTS)
        self.history_etvoc: collections.deque = collections.deque(maxlen=HISTORY_MAX_POINTS)

    def display_name(self) -> str:
        return self.name or self.address

    def is_stale(self) -> bool:
        if self.last_seen is None:
            return True
        return (time.time() - self.last_seen) > STALE_SECONDS

    def update(self, values: dict):
        now = time.time()
        if self.t0 is None:
            self.t0 = now
        self.last_seen = now

        if "rssi" in values:
            self.rssi = values["rssi"]
        if "temperature_c" in values:
            self.temperature_c = values["temperature_c"]
        if "humidity" in values:
            self.humidity = values["humidity"]
        if "eco2" in values:
            self.eco2 = int(values["eco2"])
        if "etvoc" in values:
            self.etvoc = int(values["etvoc"])
            self.aqi = aqi_from_tvoc(self.etvoc)

        rel_t = now - self.t0
        self.history_t.append(rel_t)
        self.history_temp.append(self.temperature_c)
        self.history_hum.append(self.humidity)
        self.history_aqi.append(self.aqi)
        self.history_eco2.append(self.eco2)
        self.history_etvoc.append(self.etvoc)


class KnownCubesStore:
    """Load/save named AirCubes to known_aircubes.json."""

    def __init__(self, path: str = KNOWN_FILE):
        self.path = path

    def load(self) -> dict:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def save(self, address: str, name: str):
        known = self.load()
        known[address] = {
            "name": name,
            "added": datetime.now().isoformat(timespec="seconds"),
        }
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(known, fh, indent=2)

    def forget(self, address: str):
        known = self.load()
        if address in known:
            del known[address]
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(known, fh, indent=2)


# ---------------------------------------------------------------------------
# UI widgets
# ---------------------------------------------------------------------------


class CubeCard(QFrame):
    """One row in the discovered-cubes list."""

    selected = pyqtSignal(str)
    rename_requested = pyqtSignal(str)

    def __init__(self, address: str):
        super().__init__()
        self.address = address
        self._selected = False
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(72)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        self.color_dot = QLabel()
        self.color_dot.setFixedSize(18, 18)
        self.color_dot.setStyleSheet(
            "background-color: #2e7d32; border-radius: 9px; border: 1px solid #888;"
        )

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.name_label = QLabel(self.address)
        self.name_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.name_label.setTextFormat(Qt.TextFormat.RichText)
        self.sub_label = QLabel("Waiting for data...")
        self.sub_label.setFont(QFont("Segoe UI", 9))
        self.sub_label.setStyleSheet("color: #666;")
        text_col.addWidget(self.name_label)
        text_col.addWidget(self.sub_label)

        self.rename_btn = QPushButton("Name")
        self.rename_btn.setFixedWidth(72)
        self.rename_btn.clicked.connect(self._on_rename_clicked)

        layout.addWidget(self.color_dot)
        layout.addLayout(text_col, stretch=1)
        layout.addWidget(self.rename_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.address)
        super().mousePressEvent(event)

    def _on_rename_clicked(self):
        self.rename_requested.emit(self.address)

    def set_selected(self, selected: bool):
        self._selected = selected
        if selected:
            self.setStyleSheet("QFrame { border: 2px solid #1e88e5; border-radius: 4px; }")
        else:
            self.setStyleSheet("")

    def refresh(self, state: CubeState):
        name = state.display_name()
        if not state.known:
            self.name_label.setText(f'{name} <span style="color:#888;font-style:italic;">(new)</span>')
        else:
            self.name_label.setText(name)

        aqi = state.aqi if state.aqi is not None else 0
        rating = aqi_rating(aqi) if state.aqi is not None else "—"
        rssi = f"{state.rssi} dBm" if state.rssi is not None else "— dBm"
        self.sub_label.setText(f"AQI {aqi if state.aqi is not None else '—'} — {rating} — {rssi}")
        self.color_dot.setStyleSheet(
            f"background-color: {aqi_to_hex(aqi)}; border-radius: 9px; border: 1px solid #888;"
        )
        self.rename_btn.setText("Rename" if state.known else "Name")

        if state.is_stale():
            self.sub_label.setStyleSheet("color: #999;")
            if self._selected:
                self.setStyleSheet(
                    "QFrame { border: 2px solid #90caf9; border-radius: 4px; opacity: 0.75; }"
                )
            else:
                self.setStyleSheet("QFrame { opacity: 0.75; }")
        elif self._selected:
            self.setStyleSheet("QFrame { border: 2px solid #1e88e5; border-radius: 4px; }")
        else:
            self.setStyleSheet("")
            self.sub_label.setStyleSheet("color: #666;")


class PlotCanvas(FigureCanvas):
    """Matplotlib canvas with three subplots (ported from aircube_app.py)."""

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(8, 5), dpi=100)
        self.fig.set_facecolor("#fafafa")
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax_temp_hum = self.fig.add_subplot(311)
        self.ax_aqi = self.fig.add_subplot(312, sharex=self.ax_temp_hum)
        self.ax_gases = self.fig.add_subplot(313, sharex=self.ax_temp_hum)
        self.fig.tight_layout(pad=2.0)
        self._setup_axes()

    def _setup_axes(self):
        for ax in (self.ax_temp_hum, self.ax_aqi, self.ax_gases):
            ax.set_facecolor("#ffffff")
            ax.grid(True, linestyle="--", alpha=0.7)
        self.ax_temp_hum.set_ylabel("Temp (°C) / Humidity (%)")
        self.ax_aqi.set_ylabel("AQI")
        self.ax_gases.set_ylabel("eCO2 (ppm) / eTVOC (ppb)")
        self.ax_gases.set_xlabel("Time (seconds)")

    def update_plot(self, state: CubeState | None):
        self.ax_temp_hum.cla()
        self.ax_aqi.cla()
        self.ax_gases.cla()

        if state is None or len(state.history_t) == 0:
            self._setup_axes()
            self.draw()
            return

        x = list(state.history_t)
        temp = [v if v is not None else float("nan") for v in state.history_temp]
        hum = [v if v is not None else float("nan") for v in state.history_hum]
        aqi = [v if v is not None else float("nan") for v in state.history_aqi]
        eco2 = [v if v is not None else float("nan") for v in state.history_eco2]
        etvoc = [v if v is not None else float("nan") for v in state.history_etvoc]

        self.ax_temp_hum.plot(x, temp, label="Temperature (°C)", color="#e53935", linewidth=1.5)
        self.ax_temp_hum.plot(x, hum, label="Humidity (%)", color="#1e88e5", linewidth=1.5)
        self.ax_temp_hum.set_ylabel("Temp / Humidity")
        self.ax_temp_hum.legend(loc="upper left", fontsize=8)
        self.ax_temp_hum.grid(True, linestyle="--", alpha=0.7)

        self.ax_aqi.plot(x, aqi, label="AQI", color="#7cb342", linewidth=1.5)
        self.ax_aqi.set_ylabel("AQI")
        self.ax_aqi.legend(loc="upper left", fontsize=8)
        self.ax_aqi.grid(True, linestyle="--", alpha=0.7)

        self.ax_gases.plot(x, eco2, label="eCO2 (ppm)", color="#8e24aa", linewidth=1.5)
        self.ax_gases.plot(x, etvoc, label="eTVOC (ppb)", color="#00897b", linewidth=1.5)
        self.ax_gases.set_ylabel("Gas levels")
        self.ax_gases.set_xlabel("Time (s)")
        self.ax_gases.legend(loc="upper left", fontsize=8)
        self.ax_gases.grid(True, linestyle="--", alpha=0.7)

        self.fig.tight_layout(pad=2.0)
        self.draw()


class CubeDetail(QWidget):
    """Right pane: live values, color swatch, and history for one cube."""

    def __init__(self):
        super().__init__()
        self._state: CubeState | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.title_label = QLabel("Select an AirCube")
        self.title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self.color_swatch = QFrame()
        self.color_swatch.setFixedSize(64, 64)
        self.color_swatch.setStyleSheet(
            "background-color: #cccccc; border: 1px solid #888; border-radius: 4px;"
        )
        rating_col = QVBoxLayout()
        self.rating_label = QLabel("—")
        self.rating_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Segoe UI", 9))
        self.status_label.setStyleSheet("color: #666;")
        rating_col.addWidget(self.rating_label)
        rating_col.addWidget(self.status_label)
        header.addWidget(self.title_label, stretch=1)
        header.addWidget(self.color_swatch)
        header.addLayout(rating_col)
        layout.addLayout(header)

        self.sensor_frame = QFrame()
        self.sensor_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        grid = QGridLayout(self.sensor_frame)
        grid.setSpacing(15)
        value_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        unit_font = QFont("Segoe UI", 12)
        label_font = QFont("Segoe UI", 10)

        self.temp_label = QLabel("--.-")
        self.humidity_label = QLabel("--.-")
        self.aqi_label = QLabel("---")
        self.eco2_label = QLabel("----")
        self.etvoc_label = QLabel("----")
        for lbl in (self.temp_label, self.humidity_label, self.aqi_label,
                    self.eco2_label, self.etvoc_label):
            lbl.setFont(value_font)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        specs = [
            ("Temperature", self.temp_label, "°C"),
            ("Humidity", self.humidity_label, "%"),
            ("Air Quality Index", self.aqi_label, "AQI"),
            ("eCO2", self.eco2_label, "ppm"),
            ("eTVOC", self.etvoc_label, "ppb"),
        ]
        for col, (title, value_lbl, unit) in enumerate(specs):
            title_lbl = QLabel(title)
            title_lbl.setFont(label_font)
            title_lbl.setStyleSheet("color: #666;")
            unit_lbl = QLabel(unit)
            unit_lbl.setFont(unit_font)
            box = QVBoxLayout()
            box.addWidget(title_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
            row = QHBoxLayout()
            row.addWidget(value_lbl)
            row.addWidget(unit_lbl, alignment=Qt.AlignmentFlag.AlignBottom)
            box.addLayout(row)
            grid.addLayout(box, 0, col)

        layout.addWidget(self.sensor_frame)
        self.plot = PlotCanvas(self)
        layout.addWidget(self.plot, stretch=1)

    def show_cube(self, state: CubeState):
        self._state = state
        self.title_label.setText(state.display_name())

        aqi = state.aqi if state.aqi is not None else 0
        hex_color = aqi_to_hex(aqi)
        self.color_swatch.setStyleSheet(
            f"background-color: {hex_color}; border: 1px solid #888; border-radius: 4px;"
        )
        if state.aqi is not None:
            rating = aqi_rating(state.aqi)
            self.rating_label.setText(rating)
            self.rating_label.setStyleSheet(f"color: {hex_color};")
        else:
            self.rating_label.setText("—")
            self.rating_label.setStyleSheet("color: #666;")

        if state.last_seen is not None:
            ago = int(time.time() - state.last_seen)
            stale = " (stale)" if state.is_stale() else ""
            rssi = f"{state.rssi} dBm" if state.rssi is not None else "— dBm"
            self.status_label.setText(f"RSSI {rssi} — last seen {ago}s ago{stale}")
        else:
            self.status_label.setText("Not seen yet")

        if state.temperature_c is not None:
            self.temp_label.setText(f"{state.temperature_c:.1f}")
        if state.humidity is not None:
            self.humidity_label.setText(f"{state.humidity:.1f}")
        if state.aqi is not None:
            self.aqi_label.setText(str(int(state.aqi)))
            self.aqi_label.setStyleSheet(f"color: {hex_color};")
        if state.eco2 is not None:
            self.eco2_label.setText(str(int(state.eco2)))
        if state.etvoc is not None:
            self.etvoc_label.setText(str(int(state.etvoc)))

        self.plot.update_plot(state)

    def clear(self):
        self._state = None
        self.title_label.setText("Select an AirCube")
        self.rating_label.setText("—")
        self.rating_label.setStyleSheet("color: #666;")
        self.status_label.setText("")
        self.color_swatch.setStyleSheet(
            "background-color: #cccccc; border: 1px solid #888; border-radius: 4px;"
        )
        for lbl in (self.temp_label, self.humidity_label, self.aqi_label,
                    self.eco2_label, self.etvoc_label):
            lbl.setText("—")
            lbl.setStyleSheet("")
        self.plot.update_plot(None)

    def refresh_plot(self):
        if self._state is not None:
            self.show_cube(self._state)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class AirCubeBLEMonitor(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.setMinimumSize(1000, 700)

        self.cubes: dict[str, CubeState] = {}
        self.cards: dict[str, CubeCard] = {}
        self.selected_address: str | None = None
        self.store = KnownCubesStore()
        self.known = self.store.load()
        self.scanner_thread: BLEScannerThread | None = None
        self.scanning = False

        self._build_ui()
        self._setup_timers()
        self._preload_known_cubes()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        scan_group = QGroupBox("Scanning")
        scan_row = QHBoxLayout(scan_group)
        self.scan_btn = QPushButton("Start Scan")
        self.scan_btn.setMinimumWidth(120)
        self.scan_btn.clicked.connect(self.toggle_scan)
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.scan_status = QLabel("Idle")
        self.scan_status.setStyleSheet("color: #666;")
        self.counter_label = QLabel("Discovered: 0  Known: 0")
        scan_row.addWidget(self.scan_btn)
        scan_row.addWidget(self.scan_status)
        scan_row.addSpacing(20)
        scan_row.addWidget(self.counter_label)
        scan_row.addStretch()
        main_layout.addWidget(scan_group)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.card_list_widget = QWidget()
        self.card_list_layout = QVBoxLayout(self.card_list_widget)
        self.card_list_layout.setContentsMargins(0, 0, 0, 0)
        self.card_list_layout.setSpacing(6)
        self.card_list_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.card_list_widget)
        scroll.setMinimumWidth(300)

        self.detail = CubeDetail()
        splitter.addWidget(scroll)
        splitter.addWidget(self.detail)
        splitter.setSizes([320, 680])
        main_layout.addWidget(splitter, stretch=1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready — click Start Scan to discover AirCubes")

    def _setup_timers(self):
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._on_refresh_tick)
        self.refresh_timer.start(1000)

    def _preload_known_cubes(self):
        for address, entry in self.known.items():
            name = entry.get("name", address)
            self._ensure_cube(address, name=name, known=True)
        self._update_counters()

    def _ensure_cube(self, address: str, name: str | None = None, known: bool = False) -> CubeState:
        if address in self.cubes:
            return self.cubes[address]
        state = CubeState(address, name=name, known=known)
        self.cubes[address] = state
        card = CubeCard(address)
        card.selected.connect(self.on_card_selected)
        card.rename_requested.connect(self.on_rename_requested)
        card.refresh(state)
        self.cards[address] = card
        # Insert before the trailing stretch
        idx = self.card_list_layout.count() - 1
        self.card_list_layout.insertWidget(idx, card)
        return state

    def _update_counters(self):
        discovered = len(self.cubes)
        known_count = sum(1 for c in self.cubes.values() if c.known)
        self.counter_label.setText(f"Discovered: {discovered}  Known: {known_count}")

    def toggle_scan(self):
        if self.scanning:
            if self.scanner_thread:
                self.scanner_thread.stop()
                self.scanner_thread = None
            self.scanning = False
            self.scan_btn.setText("Start Scan")
            self.scan_status.setText("Idle")
            self.status_bar.showMessage("Scan stopped")
            return

        self.scanner_thread = BLEScannerThread()
        self.scanner_thread.device_seen.connect(self.on_device_seen)
        self.scanner_thread.error_occurred.connect(self.on_scanner_error)
        self.scanner_thread.scan_state.connect(self._on_scan_state)
        self.scanner_thread.start()
        self.scanning = True
        self.scan_btn.setText("Stop Scan")
        self.scan_status.setText("Scanning...")
        self.status_bar.showMessage("Scanning for AirCubes...")

    def _on_scan_state(self, active: bool):
        if not active and self.scanning:
            self.scanning = False
            self.scan_btn.setText("Start Scan")
            self.scan_status.setText("Idle")

    def on_device_seen(self, address: str, values: dict):
        if address not in self.cubes:
            name = None
            known = False
            if address in self.known:
                name = self.known[address].get("name")
                known = True
            state = self._ensure_cube(address, name=name, known=known)
            self._update_counters()
            if self.selected_address is None:
                self.on_card_selected(address)
        else:
            state = self.cubes[address]

        state.update(values)
        self.cards[address].refresh(state)
        if address == self.selected_address:
            self.detail.show_cube(state)

    def on_card_selected(self, address: str):
        self.selected_address = address
        for addr, card in self.cards.items():
            card.set_selected(addr == address)
        if address in self.cubes:
            self.detail.show_cube(self.cubes[address])

    def on_rename_requested(self, address: str):
        state = self.cubes.get(address)
        if state is None:
            return
        default = state.name or state.address
        name, ok = QInputDialog.getText(
            self,
            "Name AirCube",
            "Enter a name for this AirCube:",
            text=default,
        )
        if ok and name.strip():
            name = name.strip()
            self.store.save(address, name)
            self.known[address] = {"name": name}
            state.name = name
            state.known = True
            self.cards[address].refresh(state)
            if address == self.selected_address:
                self.detail.show_cube(state)
            self._update_counters()
            self.status_bar.showMessage(f"Saved known AirCube: {name}")

    def on_scanner_error(self, msg: str):
        self.status_bar.showMessage(f"Scanner error: {msg}")
        QMessageBox.warning(self, "BLE Scanner Error", msg)

    def _on_refresh_tick(self):
        for address, state in self.cubes.items():
            if address in self.cards:
                self.cards[address].refresh(state)
        if self.selected_address and self.selected_address in self.cubes:
            self.detail.refresh_plot()

    def closeEvent(self, event):
        if self.scanner_thread:
            self.scanner_thread.stop()
            self.scanner_thread = None
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = AirCubeBLEMonitor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
