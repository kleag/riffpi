# Installation

This covers setting up a Raspberry Pi to run RiffPi end to end: enabling I2C, installing the
package, configuring virtual mouse input permissions, and running it as a background service.

## Hardware / OS prerequisites

- Raspberry Pi 5 (a Pi 4 should also work).
- [Pisound](https://blokas.io/pisound/) sound card.
- The MCP23017 (×2) and ADS1115 I2C peripherals wired up as described in
  [Architecture](architecture.md).

### Enable I2C and the Pisound overlay

Add to `/boot/firmware/config.txt`:

```ini
display_auto_detect=1
dtparam=i2c_arm=on
dtparam=spi=on
dtparam=i2c_arm_baudrate=400000
dtoverlay=pisound
dtoverlay=vc4-kms-v3d
usb_max_current_enable=1
```

Then enable I2C interactively and reboot:

```bash
sudo raspi-config
```

Go to `Interface Options → I2C → Enable`, then reboot.

### Verify the I2C devices are visible

```bash
sudo apt install -y i2c-tools
sudo i2cdetect -y 1
```

You should see the two MCP23017s (`0x20`, `0x21`) and the ADS1115 on the bus.

### Set up the virtual mouse device (`uinput`)

The joystick and keypad emulate mouse input via `uinput`, which needs the kernel module loaded
and the running user to have permission to open it:

```bash
sudo apt install python3-uinput
echo uinput | sudo tee -a /etc/modules
```

```bash
sudo tee /etc/udev/rules.d/99-uinput.rules <<'EOF'
KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input"
EOF
sudo usermod -a -G input $USER
```

Log out and back in (or reboot) for the group change to take effect.

## Install and autostart Guitarix

RiffPi is only the controller: the sound itself is processed by
[Guitarix](https://guitarix.org/), running on the same Pi under PipeWire's JACK emulation.

```bash
sudo apt install guitarix pipewire-jack
```

Guitarix is a GUI application, so start it from the desktop session's autostart rather than as
a systemd service (it needs the Wayland display, which systemd user services don't get by
default). Create `~/.config/autostart/guitarix.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Guitarix
Exec=sh -c "sleep 10 && pw-jack guitarix -p 7777"
```

- `pw-jack` runs Guitarix against PipeWire's JACK implementation.
- `-p 7777` opens Guitarix's JSON-RPC control port, which RiffPi uses to know how many presets
  each bank holds (see [Usage](usage.md#rotary-encoders)). It must match `GUITARIX_RPC_PORT` at
  the top of `riffpi/daemon.py`.
- `sleep 10` gives PipeWire and the Pisound time to come up after login.

The desktop session starts this at login, so on a headless pedal enable automatic desktop login
(`sudo raspi-config` → `System Options → Boot / Auto Login → Desktop Autologin`). Note that
nothing restarts Guitarix if it crashes or is closed: relaunch it from the desktop menu.

Startup order between Guitarix and RiffPi doesn't matter: RiffPi checks every 2 seconds that its
MIDI port is linked to Guitarix's (`gx_head_amp`) through PipeWire, and creates the links as soon
as Guitarix's ports appear, including after Guitarix is restarted. Until then its log shows
"Guitarix MIDI ports not available".

## Install RiffPi

```bash
pip install riffpi
```

This installs the `riffpi` command. Running `riffpi` with no arguments (or `riffpi run`) runs
the daemon directly in the foreground — useful to check everything works before setting it up as
a background service.

## Run as a systemd user service

`pip install` never installs or enables background services on its own — that's a deliberate,
separate step. `riffpi` ships a subcommand for it:

```bash
riffpi install-service
```

This writes `~/.config/systemd/user/riffpi.service` (pointing `ExecStart` at wherever `riffpi`
was actually installed), then runs the equivalent of:

```bash
systemctl --user daemon-reload
systemctl --user enable --now riffpi.service
```

so the daemon starts immediately and again on every future login. Useful follow-up commands:

```bash
systemctl --user status riffpi.service
journalctl --user-unit riffpi.service -f
systemctl --user stop riffpi.service
```

To remove it again:

```bash
riffpi uninstall-service
```

which stops, disables, and deletes the unit file.

### Starting on boot without logging in (headless)

A `systemd --user` service normally only runs while its user has an active login session. For a
pedal that should come up on boot with nobody logged in, enable "lingering" for your user once:

```bash
sudo loginctl enable-linger $USER
```

`riffpi install-service` checks this and prints a reminder if it isn't enabled yet.

### Doing it manually

If you'd rather not run the installer, or need a non-standard setup, here's the unit file it
writes, for reference:

```ini
[Unit]
Description=RiffPi Guitar Multi-Effect Daemon
After=graphical-session.target

[Service]
ExecStart=/home/<you>/.venv/bin/riffpi
WorkingDirectory=/home/<you>
Restart=on-failure

[Install]
WantedBy=default.target
```

Save it as `~/.config/systemd/user/riffpi.service` (adjusting `ExecStart` to wherever `riffpi`
was installed, e.g. `which riffpi`), then run the `systemctl --user` commands above yourself.

## Screen rotation (keypad `999`)

Typing `999` on the keypad toggles the screen between portrait and landscape (handled by
`riffpi/display.py`, which calls `wlr-randr`; Wayland desktop only, the Raspberry Pi OS default).

1. Install the tool: `sudo apt install wlr-randr`. Run `wlr-randr` to see your output's name
   (e.g. `DSI-1`).
2. Make touches follow the rotation by mapping the touchscreen to that output in
   `~/.config/labwc/rc.xml` (get the device name from `libinput list-devices`), then log out
   and back in:

    ```xml
    <touch deviceName="your touchscreen name" mapToOutput="DSI-1" />
    ```

3. If the screen comes out upside down after a toggle, set `QUARTER_TURN_TRANSFORM = "270"` at
   the top of `riffpi/display.py`. If several outputs are connected, set `DISPLAY_OUTPUT`.

The rotation is not saved: after a reboot the screen is back in its configured orientation.

## Mixer mode (keypad `998`)

Typing `998` turns the pedal's screen into the remote control of a digital mixer with a web GUI,
set up for a Soundcraft Ui24R (handled by `riffpi/mixer.py`):

- on: joins the mixer's Wi-Fi (`nmcli`), rotates to landscape, opens the GUI in Chromium kiosk
  mode;
- off: closes Chromium, rotates back to portrait, reconnects the previously active Wi-Fi.

Setup:

1. Do the [screen rotation](#screen-rotation-keypad-999) setup above.
2. Set `MIXER_WIFI_SSID` at the top of `riffpi/mixer.py` to the mixer's network name (the
   network is assumed to have no password). `MIXER_URL` defaults to `http://10.10.1.1`, the
   Ui24R's address on its own hotspot.
3. Check Chromium is installed (`sudo apt install chromium` if `chromium` isn't found).
4. Check the riffpi service is allowed to switch networks: from the pedal, type `998` and
   watch `journalctl --user-unit riffpi.service -f`. A "Not authorized" error from `nmcli`
   means NetworkManager's polkit rules don't let this user change connections outside a desktop
   session; a polkit rule granting `org.freedesktop.NetworkManager.*` to this user is then
   needed.

The first time, the Pi creates a saved connection for the mixer's network; it then joins it in a
few seconds. While in mixer mode the Pi is off your usual Wi-Fi. If the mixer is cabled to the
Pi's Ethernet port instead, set `MIXER_URL` to `http://10.10.2.1` (the Ui24R's wired default);
a failed Wi-Fi join is logged but the GUI is still opened.

## Disable WiFi power management

To avoid losing WiFi unexpectedly on the Pi, disable its power management. Create
`/etc/systemd/system/wifi-fix.service`:

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

```bash
sudo systemctl enable wifi-fix.service
sudo systemctl start wifi-fix.service
```
