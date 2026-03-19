# Wireless Light Sensor (WLS) for KDE Plasma 6

> Automatically adjusts your monitor brightness based on real ambient light
> data streamed from your Android phone over WiFi — no extra hardware,
> no camera hacks, no sudo.

```
[Android ALS chip]
       │  Sensor Server app
       │  WebSocket (WiFi)
       ▼
  WLS.py daemon
       │  org.kde.ScreenBrightness DBus
       ▼
KDE Plasma 6 brightness
  (tray slider + OSD in sync)
```

---

## Features

- Uses your phone's **dedicated ambient light sensor** (hardware chip, not camera)
- Controls **any combination of displays** — laptop screen, external monitor, or both
- Changes appear in the **KDE brightness tray slider and OSD** — fully integrated
- **System tray widget** with live lux reading, connection status, and quick toggles
- **Night mode** — caps brightness at a configurable ceiling after dark
- **EMA smoothing** — no flickering from transient light changes
- **mDNS/Zeroconf auto-discovery** — finds your phone without manual IP entry
- Auto-reconnects if the phone sleeps or WiFi drops
- Runs as a **systemd user service** — starts on login, no terminal needed

---

## Requirements

### System

- Fedora Linux 40 or 41+ (KDE Plasma 6, Wayland)
- Android phone on the same WiFi network

### Fedora packages (installed automatically by `make install`)

| Package | Purpose |
|---|---|
| `python3-pyqt6` | System tray widget — KDE/Qt6 native |
| `python3-dbus` | KDE ScreenBrightness DBus control |
| `brightnessctl` | Brightness fallback backend |

### Python packages (installed automatically by `make install`)

| Package | Purpose |
|---|---|
| `websocket-client` | WebSocket connection to Sensor Server |
| `zeroconf` | mDNS auto-discovery of phone IP |

### Android app

**Sensor Server** by Umer Farooq — free, open source, no ads

- Google Play Store → search **"Sensor Server"**
- F-Droid: `github.umer0586.sensorserver`
- GitHub: https://github.com/umer0586/SensorServer

---

## Installation

### Step 1 — Get the project files

```bash
git clone https://github.com/prasanthc41m/WLS.git
cd WLS
```

Or if you downloaded a ZIP:

```bash
unzip WLS.zip
cd WLS
```

### Step 2 — Install

```bash
make install
```

This will automatically:

1. Check for missing system packages and install them via `dnf`
2. Install missing Python packages via `pip`
3. Copy `WLS.py` → `~/.local/bin/WLS.py`
4. Copy `WLS.service` → `~/.config/systemd/user/WLS.service`
5. Reload the systemd user daemon

### Step 3 — Enable auto-start

```bash
make enable
```

WLS will now start automatically on every KDE login.

### Step 4 — Set up Sensor Server on your Android phone

1. Install **Sensor Server** from the Play Store
2. Open the app → tap **Start Server**
3. Note the IP shown, e.g. `192.168.1.5:8080`
4. *(Recommended)* Enable **Zeroconf/mDNS** in app Settings — WLS will
   find your phone automatically, no IP entry needed

### Step 5 — Connect WLS to your phone

Right-click the **WLS tray icon** → **Settings**:

- Enter your phone's IP address
- Select which display(s) to control
- Click **Save**

The tray dot turns **green** when connected. Brightness will start adjusting
automatically within a few seconds.

---

## Make targets reference

```
make install     Check deps and install WLS
make enable      Enable auto-start on login + start now
make start       Start WLS once (no auto-start)
make stop        Stop WLS
make restart     Restart WLS
make disable     Stop WLS and disable auto-start
make status      Show systemd service status
make logs        Show recent logs (journal + app log)
make uninstall   Remove WLS completely
```

---

## Settings dialog

Right-click tray icon → **Settings**

### 📱 Phone Connection

| Field | Description |
|---|---|
| IP address | Your phone's local WiFi IP from the Sensor Server app |
| Port | Default `8080` — only change if customised in the app |

### 🖥️ Display Selection

| Option | Description |
|---|---|
| All displays | Adjusts every brightness-capable display simultaneously |
| display0 | NVIDIA / external monitor |
| display1 | Built-in / laptop screen |

WLS auto-detects available displays from KDE on startup. The dropdown
shows the **current brightness** of the selected display for reference.

### ⚙️ Behaviour

| Option | Description |
|---|---|
| Auto-adjust enabled | Master on/off toggle |
| Night mode | Caps brightness at the night ceiling value |

### 🔆 Brightness Range

| Field | Description |
|---|---|
| Minimum | Lowest brightness WLS will set (default 10%) |
| Maximum | Highest brightness WLS will set (default 100%) |

### 💡 Lux Calibration

**100% brightness at** — lux reading that maps to maximum brightness:

| Value | Typical environment |
|---|---|
| 200 lux | Dim room / evening |
| 500 lux | Normal home or office |
| 1000 lux | Bright room near a window |
| 5000 lux | Outdoor / sunlit |

Start at **500** and tune to taste.

### 🎚️ Manual Override

Set brightness immediately without affecting the auto-adjust calibration.

---

## Configuration file

`~/.config/camlight/wifi_config.json`

```json
{
  "phone_ip":         "192.168.1.5",
  "phone_port":       8080,
  "enabled":          true,
  "smoothing":        0.2,
  "min_brightness":   10,
  "max_brightness":   100,
  "night_mode":       false,
  "night_cap":        40,
  "lux_max":          1000.0,
  "gamma":            1.2,
  "reconnect_sec":    5,
  "target_display":   "all"
}
```

| Key | Description |
|---|---|
| `smoothing` | EMA alpha `0.0–1.0`. Lower = slower, smoother |
| `gamma` | Curve shape. `>1` boosts mid-range brightness response |
| `night_cap` | Brightness ceiling in night mode (%) |
| `reconnect_sec` | Seconds before retrying after disconnect |
| `target_display` | `"all"`, `"display0"`, or `"display1"` |

---

## Tray icon colours

| Colour | Meaning |
|---|---|
| 🟢 Green | Connected — auto-adjusting |
| 🟠 Orange | Phone IP set, currently reconnecting |
| 🔴 Red | No phone IP configured |

---

## Logs

```bash
make logs                                         # recent journal + app log
journalctl --user -u WLS.service -f              # live journal
tail -f ~/.local/share/camlight/wifi.log         # live app log
```

---

## Troubleshooting

**Tray icon not visible**
Click the **▲** arrow in the KDE system tray to reveal hidden icons.
Drag the WLS dot to the visible area to pin it.

**Brightness not changing**
Test the DBus interface directly:

```bash
# List detected displays
qdbus org.kde.ScreenBrightness /org/kde/ScreenBrightness \
      org.kde.ScreenBrightness.DisplaysDBusNames

# Set display1 to 60% manually
qdbus org.kde.ScreenBrightness /org/kde/ScreenBrightness/display1 \
      org.kde.ScreenBrightness.Display.SetBrightness 6000 false
```

If that fails: `sudo dnf install -y python3-dbus && make restart`

**Cannot connect to phone**
- Ensure phone and laptop are on the **same WiFi network**
- Sensor Server app must show "Server started"
- Open the firewall port if needed:

```bash
sudo firewall-cmd --add-port=8080/tcp --permanent
sudo firewall-cmd --reload
```

**Phone disconnects frequently**
In Sensor Server settings, enable **"Keep screen on while server is running"**.

**Service fails to start**

```bash
make status
make logs
```

---

## Uninstall

```bash
make uninstall
```

To also remove config and logs:

```bash
rm -rf ~/.config/camlight ~/.local/share/camlight
```

---

## Project structure

```
WLS/
├── WLS.py          Main daemon + system tray widget
├── WLS.service     systemd user service unit
├── Makefile        Install, lifecycle, and uninstall
└── README.md       This file
```

---

## How it works

```
Phone ALS chip (lux reading)
  └─ Sensor Server WebSocket → JSON {"values": [340.0]}
       │
       ▼
WLS PhoneLightSensor thread
  └─ lux ──► gamma curve ──► target brightness %
       │
       ▼  EMA smoothing (prevents flicker)
WLS BrightnessDaemon (every 2 s)
  └─ BrightnessController.set(pct, display)
       │
       ▼  org.kde.ScreenBrightness DBus
       │  SetBrightness(0–10000, silent=False)
       ▼
KDE PowerDevil
  └─ Applies backlight change
  └─ Updates OSD brightness indicator
  └─ Syncs KDE tray brightness slider
```

---

## License

MIT — use freely, modify as needed.

---
Built with AI
