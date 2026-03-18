# ─────────────────────────────────────────────────────────────────────────────
#  Wireless Light Sensor (WLS) — Makefile
#  Targets: install | uninstall | enable | disable | status | logs | help
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT      := WLS.py
SERVICE     := WLS.service
BIN_DIR     := $(HOME)/.local/bin
SERVICE_DIR := $(HOME)/.config/systemd/user

.PHONY: all install uninstall enable disable start stop restart status logs deps help

all: help

# ── Install ───────────────────────────────────────────────────────────────────
install: deps
	@echo "==> Installing WLS..."
	@mkdir -p $(BIN_DIR)
	@mkdir -p $(SERVICE_DIR)
	@install -m 755 $(SCRIPT) $(BIN_DIR)/WLS.py
	@echo "    [OK] Script  -> $(BIN_DIR)/WLS.py"
	@install -m 644 $(SERVICE) $(SERVICE_DIR)/WLS.service
	@echo "    [OK] Service -> $(SERVICE_DIR)/WLS.service"
	@systemctl --user daemon-reload
	@echo "    [OK] systemd daemon reloaded"
	@echo ""
	@echo "==> Done! Next steps:"
	@echo "    make enable   -- start WLS now and on every login"
	@echo "    make start    -- start WLS once without enabling"

# ── System dependencies ───────────────────────────────────────────────────────
deps:
	@echo "==> Checking dependencies..."
	@command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found"; exit 1; }
	@MISSING=""; \
	python3 -c "import PyQt6"   2>/dev/null || MISSING="$$MISSING python3-pyqt6"; \
	python3 -c "import dbus"    2>/dev/null || MISSING="$$MISSING python3-dbus"; \
	command -v brightnessctl >/dev/null 2>&1 || MISSING="$$MISSING brightnessctl"; \
	if [ -n "$$MISSING" ]; then \
	    echo "==> Installing:$$MISSING"; \
	    sudo dnf install -y $$MISSING; \
	else \
	    echo "    [OK] System packages present"; \
	fi
	@python3 -c "import websocket" 2>/dev/null || \
	    pip install websocket-client --break-system-packages -q
	@python3 -c "import zeroconf"  2>/dev/null || \
	    pip install zeroconf --break-system-packages -q
	@echo "    [OK] Python packages ready"

# ── Lifecycle ────────────────────────────────────────────────────────────────
enable:
	@systemctl --user enable --now WLS.service
	@echo "[OK] WLS enabled and started (auto-starts on login)"

start:
	@systemctl --user start WLS.service
	@echo "[OK] WLS started"

stop:
	@systemctl --user stop WLS.service
	@echo "[OK] WLS stopped"

disable:
	@systemctl --user disable --now WLS.service
	@echo "[OK] WLS disabled"

restart:
	@systemctl --user restart WLS.service
	@echo "[OK] WLS restarted"

status:
	@systemctl --user status WLS.service

logs:
	@echo "=== systemd journal (last 40 lines) ==="
	@journalctl --user -u WLS.service -n 40 --no-pager
	@echo ""
	@echo "=== Application log ==="
	@tail -n 40 $(HOME)/.local/share/camlight/wifi.log 2>/dev/null \
	    || echo "(no log file yet)"

# ── Uninstall ────────────────────────────────────────────────────────────────
uninstall:
	@echo "==> Uninstalling WLS..."
	@systemctl --user disable --now WLS.service 2>/dev/null || true
	@rm -f  $(BIN_DIR)/WLS.py
	@rm -f  $(SERVICE_DIR)/WLS.service
	@systemctl --user daemon-reload
	@echo "    [OK] WLS removed"
	@echo "    Config/logs kept at ~/.config/camlight/ and ~/.local/share/camlight/"
	@echo "    Delete those directories manually if you want a clean slate."

# ── Help ─────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  Wireless Light Sensor (WLS)"
	@echo "  ════════════════════════════"
	@echo "  make install     Check deps and install WLS"
	@echo "  make enable      Enable auto-start on login + start now"
	@echo "  make start       Start WLS once (no auto-start)"
	@echo "  make stop        Stop WLS"
	@echo "  make restart     Restart WLS"
	@echo "  make disable     Stop WLS and disable auto-start"
	@echo "  make status      Show systemd service status"
	@echo "  make logs        Show recent logs"
	@echo "  make uninstall   Remove WLS completely"
	@echo ""
