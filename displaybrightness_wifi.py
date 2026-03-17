#!/usr/bin/env python3
"""
camlight_wifi.py
Android Phone ALS → KDE Plasma 6.2+ (Wayland) Monitor Brightness

Features:
  - Auto-detects all brightness-capable displays via org.kde.ScreenBrightness
  - Settings dialog lets you choose: All displays / display0 / display1 / etc.
  - Changes reflected in KDE tray slider & OSD (silent=False)
  - Fallback: org.kde.Solid.PowerManagement (Plasma 5 / older Plasma 6)

Install:
  sudo dnf install -y python3-pyqt6 python3-dbus
  pip install websocket-client zeroconf --break-system-packages
"""

import json, os, signal, subprocess, sys, threading, time, logging
from pathlib import Path

try:
    from zeroconf import ServiceBrowser, Zeroconf
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False

try:
    import websocket
except ImportError:
    sys.exit("ERROR: pip install websocket-client --break-system-packages")

try:
    import dbus
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False

try:
    from PyQt6.QtWidgets import (
        QApplication, QSystemTrayIcon, QMenu,
        QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QSpinBox, QLineEdit, QComboBox,
        QPushButton, QDialogButtonBox, QCheckBox,
        QGroupBox, QFrame,
    )
    from PyQt6.QtGui  import QIcon, QPixmap, QColor, QPainter, QBrush
    from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
except ImportError:
    sys.exit("ERROR: sudo dnf install -y python3-pyqt6")

# ── paths ─────────────────────────────────────────────────────────────────────
CONFIG_PATH = Path.home() / ".config" / "camlight" / "wifi_config.json"
LOG_PATH    = Path.home() / ".local"  / "share"    / "camlight" / "wifi.log"
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_PATH), level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("camlight")

LIGHT_SENSOR = "android.sensor.light"

# KDE DBus
SB_SERVICE = "org.kde.ScreenBrightness"
SB_ROOT    = "/org/kde/ScreenBrightness"
SB_IFACE   = "org.kde.ScreenBrightness.Display"
SB_MAXVAL  = 10000

PM_SERVICE = "org.kde.Solid.PowerManagement"
PM_PATH    = "/org/kde/Solid/PowerManagement/Actions/BrightnessControl"
PM_IFACE   = "org.kde.Solid.PowerManagement.Actions.BrightnessControl"

DEFAULTS = {
    "phone_ip":         "",
    "phone_port":       8080,
    "enabled":          True,
    "smoothing":        0.2,
    "min_brightness":   10,
    "max_brightness":   100,
    "night_mode":       False,
    "night_cap":        40,
    "lux_max":          1000.0,
    "gamma":            1.2,
    "reconnect_sec":    5,
    # "all" or a specific display name e.g. "display0"
    "target_display":   "all",
}


# ─────────────────────────────────────────────────────────────────────────────
class Config:
    def __init__(self):
        self.data  = dict(DEFAULTS)
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH) as f:
                    self.data.update(json.load(f))
            except Exception as e:
                log.warning(f"Config load: {e}")

    def save(self):
        with self._lock:
            with open(CONFIG_PATH, "w") as f:
                json.dump(self.data, f, indent=2)

    def __getattr__(self, k):
        if k in ("data", "_lock"):
            raise AttributeError(k)
        return self.data.get(k, DEFAULTS.get(k))

    def set(self, k, v):
        self.data[k] = v
        self.save()


# ─────────────────────────────────────────────────────────────────────────────
class BrightnessController:
    """
    Enumerates all KDE ScreenBrightness displays on init.
    set(pct, target) applies to the given display name(s) or "all".
    """

    def __init__(self):
        self._backend       = None
        self._all_displays  = []   # e.g. ["display0", "display1"]
        self._pm_max        = 100
        self._current       = {}   # display → last pct sent
        self._detect()
        log.info(f"Backend: {self._backend}  displays: {self._all_displays}")

    # ── detect ────────────────────────────────────────────────────────────────
    def _detect(self):
        if HAS_DBUS:
            # org.kde.ScreenBrightness (Plasma 6.2+)
            try:
                bus  = dbus.SessionBus()
                root = bus.get_object(SB_SERVICE, SB_ROOT)
                names = list(root.Get(
                    "org.kde.ScreenBrightness", "DisplaysDBusNames",
                    dbus_interface="org.freedesktop.DBus.Properties"
                ))
                if names:
                    self._all_displays = names
                    self._backend      = "screenbright"
                    return
            except Exception as e:
                log.warning(f"ScreenBrightness probe: {e}")

            # org.kde.Solid.PowerManagement (legacy)
            try:
                bus = dbus.SessionBus()
                obj = bus.get_object(PM_SERVICE, PM_PATH)
                mx  = int(obj.brightnessMax(dbus_interface=PM_IFACE))
                if mx > 0:
                    self._pm_max  = mx
                    self._backend = "powerdevil"
                    return
            except Exception as e:
                log.warning(f"PowerDevil probe: {e}")

        # qdbus shell fallback
        qdbus = self._qdbus()
        if qdbus:
            r = subprocess.run(
                [qdbus, SB_SERVICE, SB_ROOT,
                 "org.kde.ScreenBrightness.DisplaysDBusNames"],
                capture_output=True, text=True
            )
            if r.returncode == 0 and r.stdout.strip():
                self._all_displays = [l.strip() for l in r.stdout.splitlines() if l.strip()]
                self._backend      = "qdbus_sb"
                return

            r2 = subprocess.run(
                [qdbus, PM_SERVICE, PM_PATH, "brightnessMax"],
                capture_output=True, text=True
            )
            if r2.returncode == 0 and r2.stdout.strip().isdigit():
                self._pm_max  = int(r2.stdout.strip())
                self._backend = "qdbus_pm"
                return

        # brightnessctl last resort
        if subprocess.run(["which","brightnessctl"], capture_output=True).returncode == 0:
            if subprocess.run(["brightnessctl","g"], capture_output=True).returncode == 0:
                self._backend = "brightnessctl"
                log.warning("brightnessctl fallback — KDE tray won't sync.")
                return

        raise RuntimeError(
            "No brightness backend.\n"
            "Run: sudo dnf install -y python3-dbus"
        )

    def _qdbus(self):
        for n in ("qdbus6", "qdbus"):
            if subprocess.run(["which", n], capture_output=True).returncode == 0:
                return n
        return None

    @property
    def displays(self):
        """List of available display names, e.g. ['display0','display1']"""
        return list(self._all_displays)

    # ── resolve target list ───────────────────────────────────────────────────
    def _resolve(self, target: str) -> list:
        """Return list of display names to act on."""
        if self._backend not in ("screenbright", "qdbus_sb"):
            return []
        if target == "all":
            return self._all_displays
        if target in self._all_displays:
            return [target]
        return self._all_displays   # fallback

    # ── get (single display or first available) ───────────────────────────────
    def get(self, target: str = "all") -> int:
        displays = self._resolve(target) or self._all_displays
        disp     = displays[0] if displays else None
        try:
            if self._backend == "screenbright" and disp:
                bus = dbus.SessionBus()
                obj = bus.get_object(SB_SERVICE, f"{SB_ROOT}/{disp}")
                raw = int(obj.Get(SB_IFACE, "Brightness",
                                  dbus_interface="org.freedesktop.DBus.Properties"))
                return round(raw / SB_MAXVAL * 100)

            elif self._backend == "powerdevil":
                bus = dbus.SessionBus()
                obj = bus.get_object(PM_SERVICE, PM_PATH)
                return round(int(obj.brightness(dbus_interface=PM_IFACE)) / self._pm_max * 100)

            elif self._backend in ("qdbus_sb", "qdbus_pm"):
                qdbus = self._qdbus()
                if self._backend == "qdbus_sb" and disp:
                    r = subprocess.run(
                        [qdbus, SB_SERVICE, f"{SB_ROOT}/{disp}", f"{SB_IFACE}.Brightness"],
                        capture_output=True, text=True
                    )
                    if r.returncode == 0:
                        return round(int(r.stdout.strip()) / SB_MAXVAL * 100)
                else:
                    r = subprocess.run(
                        [qdbus, PM_SERVICE, PM_PATH, "brightness"],
                        capture_output=True, text=True
                    )
                    if r.returncode == 0:
                        return round(int(r.stdout.strip()) / self._pm_max * 100)

            elif self._backend == "brightnessctl":
                mx = int(subprocess.check_output(["brightnessctl","m"]).strip())
                cu = int(subprocess.check_output(["brightnessctl","g"]).strip())
                return round(cu / mx * 100)

        except Exception as e:
            log.error(f"get brightness: {e}")
        return 50

    # ── set ───────────────────────────────────────────────────────────────────
    def set(self, pct: int, target: str = "all"):
        pct = max(1, min(100, int(pct)))

        if self._backend in ("screenbright", "qdbus_sb"):
            displays = self._resolve(target)
            for disp in displays:
                if self._current.get(disp) == pct:
                    continue
                self._current[disp] = pct
                self._set_one(pct, disp)
        else:
            if self._current.get("_") == pct:
                return
            self._current["_"] = pct
            self._set_one(pct, None)

    def _set_one(self, pct: int, disp):
        try:
            if self._backend == "screenbright" and disp:
                raw = round(pct / 100 * SB_MAXVAL)
                bus = dbus.SessionBus()
                obj = bus.get_object(SB_SERVICE, f"{SB_ROOT}/{disp}")
                obj.SetBrightness(
                    dbus.Int32(raw), dbus.Boolean(False),
                    dbus_interface=SB_IFACE
                )
                log.debug(f"ScreenBrightness {disp} → {pct}% ({raw}/{SB_MAXVAL})")

            elif self._backend == "powerdevil":
                raw = round(pct / 100 * self._pm_max)
                bus = dbus.SessionBus()
                obj = bus.get_object(PM_SERVICE, PM_PATH)
                obj.setBrightness(dbus.Int32(raw), dbus_interface=PM_IFACE)

            elif self._backend == "qdbus_sb" and disp:
                raw   = round(pct / 100 * SB_MAXVAL)
                qdbus = self._qdbus()
                subprocess.run(
                    [qdbus, SB_SERVICE, f"{SB_ROOT}/{disp}",
                     f"{SB_IFACE}.SetBrightness", str(raw), "false"],
                    capture_output=True
                )

            elif self._backend == "qdbus_pm":
                raw   = round(pct / 100 * self._pm_max)
                qdbus = self._qdbus()
                subprocess.run(
                    [qdbus, PM_SERVICE, PM_PATH, "setBrightness", str(raw)],
                    capture_output=True
                )

            elif self._backend == "brightnessctl":
                subprocess.run(["brightnessctl","s",f"{pct}%"], capture_output=True)

        except Exception as e:
            log.error(f"_set_one {disp} {pct}%: {e}")
            self._current.pop(disp or "_", None)


# ─────────────────────────────────────────────────────────────────────────────
class PhoneLightSensor:
    def __init__(self, cfg: Config):
        self.cfg       = cfg
        self._ws       = None
        self._thread   = None
        self._running  = False
        self.last_lux  = 0.0
        self.connected = False
        self._lock     = threading.Lock()

    def _url(self):
        return (f"ws://{self.cfg.phone_ip}:{self.cfg.phone_port}"
                f"/sensor/connect?type={LIGHT_SENSOR}")

    def _on_message(self, ws, raw):
        try:
            lux = float(json.loads(raw)["values"][0])
            with self._lock:
                self.last_lux = lux
        except Exception as e:
            log.debug(f"msg: {e}")

    def _on_open(self,  ws): self.connected = True;  log.info(f"WS connected {self.cfg.phone_ip}")
    def _on_close(self, ws, c, m): self.connected = False; log.warning("WS closed")
    def _on_error(self, ws, e):    self.connected = False; log.error(f"WS error: {e}")

    def _loop(self):
        while self._running:
            if not self.cfg.phone_ip:
                time.sleep(2); continue
            try:
                ws = websocket.WebSocketApp(
                    self._url(),
                    on_open=self._on_open, on_message=self._on_message,
                    on_error=self._on_error, on_close=self._on_close,
                )
                self._ws = ws
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log.error(f"connect: {e}")
            if self._running:
                time.sleep(self.cfg.reconnect_sec)

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False
        if self._ws:
            try: self._ws.close()
            except: pass

    def read(self) -> float:
        with self._lock: return self.last_lux


# ─────────────────────────────────────────────────────────────────────────────
class BrightnessDaemon:
    def __init__(self, cfg, brightness, sensor):
        self.cfg        = cfg
        self.brightness = brightness
        self.sensor     = sensor
        self._ema       = None
        self._running   = False
        self.last_lux   = 0.0
        self.last_pct   = brightness.get(cfg.target_display)

    def _map(self, lux: float) -> int:
        norm   = min(lux / max(self.cfg.lux_max, 1.0), 1.0)
        curved = norm ** (1.0 / max(self.cfg.gamma, 0.1))
        lo, hi = self.cfg.min_brightness, self.cfg.max_brightness
        if self.cfg.night_mode:
            hi = min(hi, self.cfg.night_cap)
        return int(lo + curved * (hi - lo))

    def _step(self):
        if not self.cfg.enabled or not self.sensor.connected:
            return
        lux = self.sensor.read()
        tgt = self._map(lux)
        if self._ema is None:
            self._ema = float(tgt)
        else:
            self._ema += self.cfg.smoothing * (tgt - self._ema)
        pct           = round(self._ema)
        self.last_lux = lux
        self.last_pct = pct
        self.brightness.set(pct, self.cfg.target_display)

    def _loop(self):
        while self._running:
            self._step(); time.sleep(2.0)

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False


# ─────────────────────────────────────────────────────────────────────────────
class MDNSDiscovery:
    def __init__(self, on_found):
        self.on_found = on_found; self._zc = None

    def start(self):
        if not HAS_ZEROCONF: return
        try:
            self._zc = Zeroconf()
            ServiceBrowser(self._zc, "_websocket._tcp.local.", self)
        except Exception as e:
            log.warning(f"mDNS: {e}")

    def add_service(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name)
            if info:
                ip = ".".join(str(b) for b in info.addresses[0])
                self.on_found(ip, info.port)
        except: pass

    def remove_service(self, *_): pass
    def update_service(self, *_): pass

    def stop(self):
        if self._zc:
            try: self._zc.close()
            except: pass


# ─────────────────────────────────────────────────────────────────────────────
class _Bridge(QObject):
    reconnect = pyqtSignal()

_bridge = _Bridge()


# ═════════════════════════════════════════════════════════════════════════════
#  SETTINGS DIALOG
# ═════════════════════════════════════════════════════════════════════════════
class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, daemon: BrightnessDaemon,
                 sensor: PhoneLightSensor,
                 brightness: BrightnessController, parent=None):
        super().__init__(parent)
        self.cfg        = cfg
        self.daemon     = daemon
        self.sensor     = sensor
        self.brightness = brightness
        self.setWindowTitle("CamLight WiFi — Settings")
        self.setMinimumWidth(480)
        self._build()

    def _sec(self, title: str) -> QLabel:
        lbl = QLabel(f"<b>{title}</b>")
        lbl.setStyleSheet("color: palette(highlight); margin-top: 8px;")
        return lbl

    def _hr(self) -> QFrame:
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color: palette(mid);")
        return f

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(8); root.setContentsMargins(20, 20, 20, 20)

        # ── 1. Phone connection ───────────────────────────────────────────────
        root.addWidget(self._sec("📱  Phone Connection"))
        g1 = QGridLayout(); g1.setColumnStretch(1, 1)

        self.ip_edit = QLineEdit(self.cfg.phone_ip or "")
        self.ip_edit.setPlaceholderText("192.168.1.x  (shown in Sensor Server app)")
        g1.addWidget(QLabel("IP address:"), 0, 0)
        g1.addWidget(self.ip_edit,          0, 1)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.cfg.phone_port)
        g1.addWidget(QLabel("Port:"), 0, 2)
        g1.addWidget(self.port_spin,  0, 3)
        root.addLayout(g1)
        root.addWidget(self._hr())

        # ── 2. Display selection ──────────────────────────────────────────────
        root.addWidget(self._sec("🖥️  Display Selection"))

        disp_row = QHBoxLayout()
        disp_row.addWidget(QLabel("Control:"))

        self.disp_combo = QComboBox()
        displays = self.brightness.displays

        # Populate combo with friendly names
        self.disp_combo.addItem("🖥️  All displays", userData="all")
        for d in displays:
            # Guess friendly label from known names
            label = self._display_label(d, displays)
            self.disp_combo.addItem(label, userData=d)

        # Select saved target
        saved = self.cfg.target_display
        for i in range(self.disp_combo.count()):
            if self.disp_combo.itemData(i) == saved:
                self.disp_combo.setCurrentIndex(i)
                break

        disp_row.addWidget(self.disp_combo)
        disp_row.addStretch()
        root.addLayout(disp_row)

        # Display info label
        self.disp_info = QLabel()
        self.disp_info.setStyleSheet("color: palette(mid); font-size: 11px;")
        self._update_disp_info()
        self.disp_combo.currentIndexChanged.connect(self._update_disp_info)
        root.addWidget(self.disp_info)
        root.addWidget(self._hr())

        # ── 3. Behaviour ──────────────────────────────────────────────────────
        root.addWidget(self._sec("⚙️  Behaviour"))
        self.chk_en    = QCheckBox("Auto-adjust brightness enabled")
        self.chk_night = QCheckBox(f"Night mode  (cap brightness at {self.cfg.night_cap}%)")
        self.chk_en.setChecked(self.cfg.enabled)
        self.chk_night.setChecked(self.cfg.night_mode)
        root.addWidget(self.chk_en)
        root.addWidget(self.chk_night)
        root.addWidget(self._hr())

        # ── 4. Brightness range ───────────────────────────────────────────────
        root.addWidget(self._sec("🔆  Brightness Range"))
        br = QHBoxLayout()
        self.mn = QSpinBox(); self.mn.setRange(1,50);  self.mn.setValue(self.cfg.min_brightness); self.mn.setSuffix(" %")
        self.mx = QSpinBox(); self.mx.setRange(50,100);self.mx.setValue(self.cfg.max_brightness); self.mx.setSuffix(" %")
        br.addWidget(QLabel("Minimum:")); br.addWidget(self.mn)
        br.addSpacing(24)
        br.addWidget(QLabel("Maximum:")); br.addWidget(self.mx)
        br.addStretch()
        root.addLayout(br)
        root.addWidget(self._hr())

        # ── 5. Lux calibration ────────────────────────────────────────────────
        root.addWidget(self._sec("💡  Lux Calibration"))
        lr = QHBoxLayout()
        self.lux = QSpinBox(); self.lux.setRange(50,20000); self.lux.setSingleStep(50)
        self.lux.setValue(int(self.cfg.lux_max)); self.lux.setSuffix(" lux")
        lr.addWidget(QLabel("100% brightness at:"))
        lr.addWidget(self.lux)
        lr.addWidget(QLabel("  dim≈200 · office≈500 · bright≈1000"))
        lr.addStretch()
        root.addLayout(lr)
        root.addWidget(self._hr())

        # ── 6. Manual override ────────────────────────────────────────────────
        root.addWidget(self._sec("🎚️  Manual Override"))
        mr = QHBoxLayout()
        self.man = QSpinBox(); self.man.setRange(1,100)
        self.man.setValue(self.daemon.last_pct); self.man.setSuffix(" %")
        btn = QPushButton("Apply now")
        btn.clicked.connect(self._apply_manual)
        mr.addWidget(QLabel("Set brightness:")); mr.addWidget(self.man)
        mr.addWidget(btn); mr.addStretch()
        root.addLayout(mr)

        root.addStretch()

        # ── Buttons ───────────────────────────────────────────────────────────
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _display_label(self, dname: str, all_displays: list) -> str:
        """Build a friendly label. display0 = external NVIDIA, display1 = built-in."""
        # Map based on known hardware from user's system
        friendly = {
            "display0": "display0  (NVIDIA / external)",
            "display1": "display1  (built-in / laptop)",
        }
        return friendly.get(dname, dname)

    def _update_disp_info(self):
        target = self.disp_combo.currentData()
        displays = self.brightness.displays
        if target == "all":
            info = f"Controls all {len(displays)} display(s): {', '.join(displays)}"
        else:
            # Show current brightness of selected display
            try:
                pct = self.brightness.get(target)
                info = f"Current brightness: {pct}%"
            except Exception:
                info = ""
        self.disp_info.setText(info)

    def _apply_manual(self):
        target = self.disp_combo.currentData() or "all"
        v = self.man.value()
        self.brightness.set(v, target)
        self.daemon._ema = float(v)

    def _save(self):
        ip_changed     = self.ip_edit.text().strip() != self.cfg.phone_ip
        target_changed = self.disp_combo.currentData() != self.cfg.target_display

        self.cfg.set("phone_ip",        self.ip_edit.text().strip())
        self.cfg.set("phone_port",      self.port_spin.value())
        self.cfg.set("target_display",  self.disp_combo.currentData())
        self.cfg.set("enabled",         self.chk_en.isChecked())
        self.cfg.set("night_mode",      self.chk_night.isChecked())
        self.cfg.set("min_brightness",  self.mn.value())
        self.cfg.set("max_brightness",  self.mx.value())
        self.cfg.set("lux_max",         float(self.lux.value()))

        if target_changed:
            self.daemon._ema = None   # re-ramp to new display's level

        if ip_changed:
            self.daemon._ema = None
            _bridge.reconnect.emit()

        self.accept()


# ═════════════════════════════════════════════════════════════════════════════
#  SYSTEM TRAY
# ═════════════════════════════════════════════════════════════════════════════
class CamLightTray:
    GREEN  = "#27ae60"
    ORANGE = "#e67e22"
    RED    = "#e74c3c"

    def __init__(self, app, daemon, sensor, cfg, brightness):
        self.app        = app
        self.daemon     = daemon
        self.sensor     = sensor
        self.cfg        = cfg
        self.brightness = brightness

        self._tray = QSystemTrayIcon(self._dot(self.RED), app)
        self._tray.setToolTip("CamLight WiFi")
        self._build_menu()
        self._tray.show()

        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

        _bridge.reconnect.connect(self._do_reconnect)

        if not cfg.phone_ip:
            QTimer.singleShot(1200, self._hint)

    def _dot(self, color: str) -> QIcon:
        px = QPixmap(22, 22); px.fill(Qt.GlobalColor.transparent)
        p  = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(color))); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(3, 3, 16, 16); p.end()
        return QIcon(px)

    def _build_menu(self):
        menu = QMenu()

        self._st = menu.addAction("● Starting…")
        self._st.setEnabled(False)
        f = self._st.font(); f.setItalic(True); self._st.setFont(f)
        menu.addSeparator()

        menu.addAction("⚙️  Settings…").triggered.connect(self._open_settings)
        menu.addSeparator()

        self._en = menu.addAction("✅  Auto-adjust  ON")
        self._en.setCheckable(True); self._en.setChecked(self.cfg.enabled)
        self._en.toggled.connect(self._tog_en)

        self._nm = menu.addAction(f"🌙  Night mode  (≤{self.cfg.night_cap}%)")
        self._nm.setCheckable(True); self._nm.setChecked(self.cfg.night_mode)
        self._nm.toggled.connect(self._tog_nm)
        menu.addSeparator()

        menu.addAction("✖  Quit").triggered.connect(self._quit)
        self._tray.setContextMenu(menu)

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self.daemon, self.sensor, self.brightness)
        dlg.exec()
        for act, val in ((self._en, self.cfg.enabled), (self._nm, self.cfg.night_mode)):
            act.blockSignals(True); act.setChecked(val); act.blockSignals(False)
        self._refresh()

    def _tog_en(self, c):
        self.cfg.set("enabled", c)
        self._en.setText("✅  Auto-adjust  ON" if c else "⬜  Auto-adjust  OFF")

    def _tog_nm(self, c):
        self.cfg.set("night_mode", c); self.daemon._ema = None

    def _do_reconnect(self):
        self.sensor.stop(); self.sensor.start()

    def _quit(self):
        self.daemon.stop(); self.sensor.stop(); self.app.quit()

    def _refresh(self):
        tgt = self.cfg.target_display
        tgt_label = "all displays" if tgt == "all" else tgt

        if self.sensor.connected:
            col = self.GREEN
            st  = (f"📱 {self.cfg.phone_ip}"
                   f"  |  {self.daemon.last_lux:.0f} lux"
                   f"  →  {self.daemon.last_pct}%"
                   f"  [{tgt_label}]")
        elif self.cfg.phone_ip:
            col = self.ORANGE
            st  = f"⚠  Reconnecting to {self.cfg.phone_ip}…"
        else:
            col = self.RED
            st  = "⚙  Open Settings → enter Phone IP"

        en = "ON" if self.cfg.enabled else "OFF"
        nm = " 🌙" if self.cfg.night_mode else ""
        self._st.setText(f"  {st}   [{en}{nm}]")
        self._tray.setIcon(self._dot(col))
        self._tray.setToolTip(f"CamLight WiFi\n{st}")

    def _hint(self):
        self._tray.showMessage(
            "CamLight WiFi — Setup needed",
            "Right-click → Settings\n"
            "• Enter your phone IP\n"
            "• Choose which display to control",
            QSystemTrayIcon.MessageIcon.Information, 8000,
        )


# ═════════════════════════════════════════════════════════════════════════════
def main():
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

    cfg        = Config()
    brightness = BrightnessController()
    sensor     = PhoneLightSensor(cfg)
    daemon     = BrightnessDaemon(cfg, brightness, sensor)

    def on_mdns(ip, port):
        if not cfg.phone_ip:
            cfg.set("phone_ip", ip); cfg.set("phone_port", port)
            log.info(f"mDNS: {ip}:{port}")
            _bridge.reconnect.emit()

    disc = MDNSDiscovery(on_mdns); disc.start()
    sensor.start(); daemon.start()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("CamLight WiFi")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print(f"No system tray. Config: {CONFIG_PATH}\nCtrl+C to quit.")
        try:
            while True:
                s = "✓" if sensor.connected else "✗"
                print(f"\r{s} lux:{daemon.last_lux:6.1f}  "
                      f"brightness:{daemon.last_pct:3d}%  "
                      f"target:{cfg.target_display}   ",
                      end="", flush=True)
                time.sleep(2)
        except KeyboardInterrupt:
            pass
        daemon.stop(); sensor.stop(); disc.stop(); return

    tray = CamLightTray(app, daemon, sensor, cfg, brightness)
    signal.signal(signal.SIGTERM, lambda *_: tray._quit())
    signal.signal(signal.SIGINT,  lambda *_: tray._quit())
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
