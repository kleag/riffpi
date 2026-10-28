#!/usr/bin/env python3
"""Toggle the touchscreen between portrait and landscape (Wayland, via `wlr-randr`).

Used by the keypad's `999` code, so the pedal's screen can be turned to landscape to drive
another device's GUI (e.g. a digital mixer's web page) and back to portrait for Guitarix,
without having to reach the desktop's screen settings on the touchscreen.

Only the display is rotated here. For touches to follow, the touch device must be mapped to the
output in the compositor's config (labwc: `<touch deviceName="..." mapToOutput="DSI-1" />` in
`~/.config/labwc/rc.xml`), see docs/installation.md.
"""
import glob
import logging
import os
import re
import subprocess
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Output to rotate (as listed by `wlr-randr`, e.g. "DSI-1" or "HDMI-A-1"). None picks the first
# enabled output.
DISPLAY_OUTPUT: Optional[str] = None

# Quarter-turn transform used when switching to a sideways orientation not seen yet since riffpi
# started. If the screen comes out upside down after a toggle, set this to "270".
QUARTER_TURN_TRANSFORM = "90"

TRANSFORM_DEGREES = {"normal": 0, "90": 90, "180": 180, "270": 270}

# Transform last used for each orientation ("portrait"/"landscape"), so toggling back restores
# exactly what was there before rather than a possibly upside-down equivalent.
_known_transforms: Dict[str, str] = {}


def _wayland_env() -> Dict[str, str]:
    """Environment for wlr-randr. A systemd --user service usually lacks WAYLAND_DISPLAY, so
    find the compositor's socket in XDG_RUNTIME_DIR ourselves."""
    env = dict(os.environ)
    runtime_dir = env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if "WAYLAND_DISPLAY" not in env:
        sockets = sorted(
            p for p in glob.glob(os.path.join(runtime_dir, "wayland-*")) if not p.endswith(".lock")
        )
        if sockets:
            env["WAYLAND_DISPLAY"] = os.path.basename(sockets[0])
    return env


def _query_output(env: Dict[str, str]) -> Optional[Tuple[str, int, int, str]]:
    """Return (output name, native width, native height, transform) of the output to rotate."""
    result = subprocess.run(
        ["wlr-randr"], env=env, capture_output=True, text=True, timeout=5, check=True
    )
    outputs = []
    current = None
    for line in result.stdout.splitlines():
        if line and not line[0].isspace():
            current = {"name": line.split()[0], "enabled": True}
            outputs.append(current)
        elif current is not None:
            stripped = line.strip()
            if stripped.startswith("Enabled:"):
                current["enabled"] = stripped.endswith("yes")
            elif stripped.startswith("Transform:"):
                current["transform"] = stripped.split(":", 1)[1].strip()
            elif "current" in stripped and (m := re.match(r"(\d+)x(\d+) px", stripped)):
                current["size"] = (int(m.group(1)), int(m.group(2)))

    for out in outputs:
        if DISPLAY_OUTPUT is not None and out["name"] != DISPLAY_OUTPUT:
            continue
        if not out["enabled"] or "size" not in out:
            continue
        width, height = out["size"]
        return out["name"], width, height, out.get("transform", "normal")
    return None


def _orientation(width: int, height: int, transform: str) -> str:
    """Orientation as seen on screen, given the mode's native (unrotated) size."""
    if TRANSFORM_DEGREES.get(transform, 0) in (90, 270):
        width, height = height, width
    return "landscape" if width > height else "portrait"


def toggle_orientation() -> None:
    """Switch the screen from portrait to landscape or back. Logs (doesn't raise) on failure."""
    env = _wayland_env()
    try:
        info = _query_output(env)
        if info is None:
            logger.error(f"toggle_orientation: no enabled output found (wanted {DISPLAY_OUTPUT})")
            return
        name, width, height, transform = info
        orientation = _orientation(width, height, transform)
        target = "portrait" if orientation == "landscape" else "landscape"
        _known_transforms[orientation] = transform

        new_transform = _known_transforms.get(target)
        if new_transform is None:
            # Sideways if the target orientation is the opposite of the panel's native one.
            native = "landscape" if width > height else "portrait"
            new_transform = "normal" if target == native else QUARTER_TURN_TRANSFORM

        logger.info(f"Rotating {name} to {target} (transform {transform} -> {new_transform})")
        subprocess.run(
            ["wlr-randr", "--output", name, "--transform", new_transform],
            env=env, capture_output=True, text=True, timeout=5, check=True,
        )
    except FileNotFoundError:
        logger.error("toggle_orientation: wlr-randr not installed (sudo apt install wlr-randr)")
    except subprocess.CalledProcessError as e:
        logger.error(f"toggle_orientation: wlr-randr failed: {e.stderr.strip()}")
    except subprocess.TimeoutExpired:
        logger.error("toggle_orientation: wlr-randr timed out")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    toggle_orientation()
