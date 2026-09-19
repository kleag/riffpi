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
