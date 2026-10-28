#!/usr/bin/env python3
"""Mixer mode: use the pedal's screen as the remote control of a digital mixer's web GUI.

Used by the keypad's `998` code. Turning it on joins the mixer's own Wi-Fi network (via
NetworkManager's `nmcli`), rotates the screen to landscape and opens the mixer's web GUI full
screen in Chromium. Turning it off closes the browser, rotates back to portrait and reconnects to
the Wi-Fi connection that was active before.

Set up for a Soundcraft Ui24R (web GUI at 10.10.1.1 on its hotspot); set MIXER_WIFI_SSID to the
mixer's network name. The network is assumed to be open (no password).
"""
import logging
import os
import shutil
import subprocess
import threading
from typing import Optional

from riffpi.display import set_orientation, wayland_env

logger = logging.getLogger(__name__)

# Name (SSID) of the mixer's Wi-Fi network. Set it to the name shown in your phone's or the Pi's
# Wi-Fi list.
MIXER_WIFI_SSID = "Soundcraft Ui24"

# Address of the mixer's web GUI on its hotspot (Soundcraft Ui24R default).
MIXER_URL = "http://10.10.1.1"

# Max time (seconds) to wait for a Wi-Fi connection to come up.
WIFI_CONNECT_TIMEOUT = 30

# Separate Chromium profile, so the kiosk window is a new browser instance rather than a tab
# handed over to an already running Chromium (which would ignore --kiosk and exit at once,
# leaving us nothing to close when leaving mixer mode).
CHROMIUM_PROFILE_DIR = "~/.cache/riffpi/mixer-chromium"

_active = False
_browser: Optional[subprocess.Popen] = None
_previous_wifi: Optional[str] = None
# Held while switching, which takes several seconds; extra key presses meanwhile are ignored.
_switch_lock = threading.Lock()


def _nmcli(*args: str, timeout: float = 10) -> str:
    result = subprocess.run(
        ["nmcli", *args], capture_output=True, text=True, timeout=timeout, check=True
    )
    return result.stdout


def _active_wifi_connection() -> Optional[str]:
    """Name of the currently active Wi-Fi connection profile, if any."""
    for line in _nmcli("-t", "-f", "NAME,TYPE", "connection", "show", "--active").splitlines():
        # Terse output escapes ':' inside names as '\:', so split on the last separator.
        name, _, conn_type = line.rpartition(":")
        if conn_type == "802-11-wireless":
            return name.replace("\\:", ":")
    return None


def _connect_mixer_wifi() -> None:
    """Bring up the mixer's network, creating the connection profile on first use."""
    try:
        _nmcli("connection", "up", "id", MIXER_WIFI_SSID, timeout=WIFI_CONNECT_TIMEOUT)
    except subprocess.CalledProcessError:
        logger.info(f"No saved connection for '{MIXER_WIFI_SSID}', scanning for it")
        _nmcli("device", "wifi", "rescan", timeout=WIFI_CONNECT_TIMEOUT)
        _nmcli("device", "wifi", "connect", MIXER_WIFI_SSID, timeout=WIFI_CONNECT_TIMEOUT)


def _open_browser() -> Optional[subprocess.Popen]:
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium is None:
        logger.error("Mixer mode: Chromium not found (sudo apt install chromium)")
        return None
    profile_dir = os.path.expanduser(CHROMIUM_PROFILE_DIR)
    return subprocess.Popen(
        [
            chromium,
            "--kiosk",
            "--noerrdialogs",
            "--disable-infobars",
            "--no-first-run",
            "--ozone-platform-hint=auto",
            f"--user-data-dir={profile_dir}",
            MIXER_URL,
        ],
        env=wayland_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _close_browser() -> None:
    global _browser
    if _browser is not None and _browser.poll() is None:
        _browser.terminate()
        try:
            _browser.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _browser.kill()
    _browser = None


def _enter() -> None:
    global _active, _browser, _previous_wifi
    logger.info(f"Entering mixer mode (Wi-Fi '{MIXER_WIFI_SSID}', {MIXER_URL})")
    _previous_wifi = _active_wifi_connection()
    if _previous_wifi == MIXER_WIFI_SSID:
        _previous_wifi = None
    try:
        _connect_mixer_wifi()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        # Still open the GUI: the mixer may be reachable some other way (e.g. Ethernet cable).
        stderr = getattr(e, "stderr", "") or ""
        logger.error(f"Mixer mode: could not join '{MIXER_WIFI_SSID}': {stderr.strip() or e}")
    set_orientation("landscape")
    _browser = _open_browser()
    _active = True


def _leave() -> None:
    global _active, _previous_wifi
    logger.info("Leaving mixer mode")
    _close_browser()
    set_orientation("portrait")
    try:
        if _previous_wifi is not None:
            _nmcli("connection", "up", "id", _previous_wifi, timeout=WIFI_CONNECT_TIMEOUT)
        elif _active_wifi_connection() == MIXER_WIFI_SSID:
            # Nothing to go back to explicitly: drop the mixer's network and let
            # NetworkManager autoconnect to whatever known network is around.
            _nmcli("connection", "down", "id", MIXER_WIFI_SSID)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = getattr(e, "stderr", "") or ""
        logger.error(f"Mixer mode: could not restore Wi-Fi: {stderr.strip() or e}")
    _previous_wifi = None
    _active = False


def _toggle() -> None:
    try:
        if _active:
            _leave()
        else:
            _enter()
    except FileNotFoundError as e:
        logger.error(f"Mixer mode: missing program: {e.filename}")
    finally:
        _switch_lock.release()


def toggle_mixer_mode() -> None:
    """Enter or leave mixer mode in a background thread (switching Wi-Fi takes seconds and
    must not block the caller, e.g. the keypad scan loop)."""
    if not _switch_lock.acquire(blocking=False):
        logger.info("Mixer mode switch already in progress, ignoring")
        return
    threading.Thread(target=_toggle, daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    toggle_mixer_mode()
    input("Mixer mode on. Press Enter to leave it...\n")
    toggle_mixer_mode()
    # Let the background thread finish before exiting.
    with _switch_lock:
        pass
