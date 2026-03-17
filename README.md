# DisplayBrightness WiFi — Android Phone ALS → Fedora Monitor Brightness
> Zero hardware cost. Uses your Android phone's built-in Ambient Light
> Sensor streamed over WiFi via the free "Sensor Server" app.

```
[Android ALS] ──WiFi WebSocket──▶ [displaybrightness_wifi.py] ──brightnessctl──▶ [Monitor]
```

---

## Step 1 — Android: Install Sensor Server

1. Open **Google Play Store**
2. Search **"Sensor Server"** by *Umer Farooq* (free, open source)
   - Or install from F-Droid: `github.umer0586.sensorserver`
3. Open the app → tap **Start Server**
4. Note the **IP address and port** shown (e.g. `192.168.1.5:8080`)
5. Keep the app open and screen on (or disable screen timeout for it)

> **Tip:** Enable **"Keep screen on while server is running"** in app settings.
> Also enable **"Zeroconf/mDNS"** in settings for auto-discovery (no IP needed).

---

## Step 2 — Fedora: Install dependencies

```bash
sudo dnf install -y python3-pyqt6 python3-dbus
pip install websocket-client zeroconf --break-system-packages

```
---

## Step 3 — Install the script

```bash
mkdir -p ~/.local/bin
cp displaybrightness_wifi.py ~/.local/bin/displaybrightness_wifi.py
chmod +x ~/.local/bin/displaybrightness_wifi.py
```

---

## Step 4 — Install systemd service (auto-start on login)

```bash
mkdir -p ~/.config/systemd/user
cp displaybrightness_wifi.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now displaybrightness_wifi.service

# Check status:
systemctl --user status displaybrightness_wifi.service
```

---

## Step 5 — Set your phone's IP in the tray

1. A **WiFi/network icon** appears in your system tray
2. Right-click → **"Set Phone IP…"**
3. Enter the IP shown in the Sensor Server app (e.g. `192.168.1.5`)

> **If you enabled mDNS in Sensor Server:** the IP is auto-discovered and
> you can skip this step entirely!

---

## Tray Menu Reference

| Item | What it does |
|---|---|
| Status line | Shows connection state, live lux, applied brightness |
| Set Phone IP… | Enter/change your phone's IP address |
| Auto-adjust enabled | Toggle auto-brightness on/off |
| Night mode | Cap brightness at 40% (configurable) |
| Brightness bounds… | Set min/max brightness % |
| Max lux scale… | Lux value that maps to 100% brightness |
| Set brightness now… | Manual one-shot override |

---

## Configuration file

`~/.config/displaybrightness/wifi_config.json`

```json
{
  "phone_ip":       "192.168.1.5",
  "phone_port":     8080,
  "enabled":        true,
  "smoothing":      0.2,
  "min_brightness": 10,
  "max_brightness": 100,
  "night_mode":     false,
  "night_cap":      40,
  "lux_max":        5000.0,
  "gamma":          1.2,
  "reconnect_sec":  5
}
```

| Key | Description |
|---|---|
| `lux_max` | Lux = 100% brightness. Indoors ~300–1000, outdoors ~5000–10000 |
| `smoothing` | EMA alpha 0–1. Lower = slower/smoother. 0.2 is good |
| `gamma` | >1 boosts mid-range brightness response |
| `reconnect_sec` | Seconds before retrying after disconnect |

---

## How lux values map to brightness

Android light sensors return real lux (SI unit):

| Environment | Typical lux |
|---|---|
| Moonlit night | 0.1 |
| Dim room | 50–150 |
| Normal office | 300–500 |
| Bright room | 1000 |
| Outdoor overcast | 5000–10000 |
| Direct sunlight | 50000+ |

Set `lux_max` to match your brightest normal indoor condition — usually
**500–1000 lux** works well for home/office use.

---

## Troubleshooting

**Tray icon not visible on GNOME:**
```bash
sudo dnf install gnome-shell-extension-appindicator
# Enable in GNOME Extensions app, then log out/in
```

**"Connection refused" / not connecting:**
- Make sure phone and laptop are on the **same WiFi network**
- Check Sensor Server app is running and shows "Server started"
- Verify IP matches what the app shows
- Check firewall: `sudo firewall-cmd --add-port=8080/tcp --permanent`

**Reconnects constantly:**
- Prevent phone screen from sleeping (in Sensor Server settings)
- Or use phone's hotspot instead of home WiFi

**mDNS not working:**
- Enable Zeroconf in Sensor Server app settings
- Install zeroconf: `pip install zeroconf --break-system-packages`

**View logs:**
```bash
tail -f ~/.local/share/displaybrightness/wifi.log
journalctl --user -u displaybrightness_wifi.service -f
```

---

## Phone battery tip

Sensor Server uses very little battery (ALS is passive hardware).
The screen is the main drain — use a phone stand near your desk
and enable "stay awake" only for the Sensor Server app using
**Tasker** or **MacroDroid** to toggle it automatically.

---

## Uninstall

```bash
systemctl --user disable --now displaybrightness_wifi.service
rm ~/.config/systemd/user/displaybrightness_wifi.service
rm ~/.local/bin/displaybrightness_wifi.py
rm -rf ~/.config/displaybrightness
```
