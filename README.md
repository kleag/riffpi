# Kleag's MFX




ADS1115
MCP23017
https://github.com/adafruit/Adafruit-MCP23017-Arduino-Library#pin-addressing

KY-040
n°4 on MCP@0x20
    - sw pin B1 (9)
    - but on A0, B0 (0, 8)

Pisound
Raspberry Pi 5 (4 should be OK)

Joystick: ADS.P0, ADS.P1
sudo apt install python3-uinput
sudo nano /etc/modules
uinput

Expression Pedal: ADS.P2

sudo nano /etc/udev/rules.d/99-uinput.rules
KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input"
sudo usermod -a -G input $USER

`/boot/firmware/config.txt`:
```
display_auto_detect=1
dtparam=i2c_arm=on
dtparam=spi=on
dtparam=i2c_arm_baudrate=400000
dtoverlay=
dtoverlay=pisound
dtoverlay=vc4-kms-v3d
usb_max_current_enable=1
```

sudo raspi-config
```

Then go to:
`Interface Options → I2C → Enable → Reboot the Pi.`

```bash
sudo apt install -y i2c-tools
```

```bash
sudo i2cdetect -y 1
```

Install the package (this provides the `riffpi` command):
```bash
pip install riffpi
```

Set it up as a background service (writes and enables a `systemd --user` unit):
```bash
riffpi install-service
```

See [docs/installation.md](docs/installation.md) for the full setup (including headless/no-login
boot) and how to uninstall it.

# Disable wlan power management 
To avoid losing Wifi unexpectedly, disable its power management. Create `/etc/systemd/system/wifi-fix.service`:


```ini
[Unit]
Description=Disable WiFi Power Management
After=network.target

[Service]
Type=oneshot
ExecStart=/sbin/iwconfig wlan0 power off
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

and then enable the new service:
```bash
sudo systemctl enable wifi-fix.service
sudo systemctl start wifi-fix.service
```

# License

Copyright Gaël de Chalendar, 2025-2026.
This source describes Open Hardware and is licensed under the CERN-OHL-
W v2.
You may redistribute and modify this documentation and make products
using it under the terms of the CERN-OHL-W v2 (https:/cern.ch/cern-ohl).
This documentation is distributed WITHOUT ANY EXPRESS OR IMPLIED
WARRANTY, INCLUDING OF MERCHANTABILITY, SATISFACTORY QUALITY
AND FITNESS FOR A PARTICULAR PURPOSE. Please see the CERN-OHL-W v2
for applicable conditions.
Source location: https://github.com/kleag/kleagmfx
As per CERN-OHL-W v2 section 4.1, should You produce hardware based on
these sources, You must maintain the Source Location visible on the
external case of the Kleag's MFX or other product you make using
this documentation.

