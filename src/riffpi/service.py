#!/usr/bin/env python3
"""Install/uninstall the riffpi systemd --user service."""
import getpass
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "riffpi.service"

UNIT_TEMPLATE = """\
[Unit]
Description=RiffPi Guitar Multi-Effect Daemon
After=graphical-session.target

[Service]
ExecStart={exec_start}
WorkingDirectory={working_directory}
Restart=on-failure

[Install]
WantedBy=default.target
"""


def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME


def _riffpi_executable() -> str:
    """Absolute path to the installed `riffpi` console script.

    Prefer the path this process was actually invoked with (argv[0], set by the
    console-script wrapper) since it's guaranteed to be the right one for whatever
    venv/pipx environment riffpi was installed into; fall back to a PATH lookup.
    """
    candidate = sys.argv[0] if Path(sys.argv[0]).name == "riffpi" else shutil.which("riffpi")
    if not candidate:
        raise RuntimeError("Could not locate the 'riffpi' executable on PATH.")
    return str(Path(candidate).resolve())


def _linger_enabled() -> bool:
    try:
        result = subprocess.run(
            ["loginctl", "show-user", "--value", "--property=Linger"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() == "yes"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install_service() -> None:
    """Write, enable, and start the riffpi systemd --user service for the current user."""
    unit_path = _unit_path()
    unit_path.parent.mkdir(parents=True, exist_ok=True)

    unit_path.write_text(
        UNIT_TEMPLATE.format(exec_start=_riffpi_executable(), working_directory=str(Path.home()))
    )
    print(f"Wrote {unit_path}")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", SERVICE_NAME], check=True)
    print(f"{SERVICE_NAME} enabled and started.")
    print(f"Check status with: systemctl --user status {SERVICE_NAME}")
    print(f"Follow logs with:  journalctl --user-unit {SERVICE_NAME} -f")

    if not _linger_enabled():
        print(
            "\nNote: systemd --user services normally only run while you're logged in. "
            "For a pedal that should start on boot without an interactive login, also run:\n"
            f"  sudo loginctl enable-linger {getpass.getuser()}"
        )


def uninstall_service() -> None:
    """Stop, disable, and remove the riffpi systemd --user service."""
    subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE_NAME], check=False)

    unit_path = _unit_path()
    if unit_path.exists():
        unit_path.unlink()
        print(f"Removed {unit_path}")
    else:
        print(f"{unit_path} did not exist, nothing to remove.")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print(f"{SERVICE_NAME} uninstalled.")
