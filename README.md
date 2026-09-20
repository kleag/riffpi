# RiffPi

![RiffPi](docs/images/riffpi-banner.svg)

[![docs](https://github.com/kleag/riffpi/actions/workflows/docs.yml/badge.svg)](https://github.com/kleag/riffpi/actions/workflows/docs.yml)
[![lint-and-build](https://github.com/kleag/riffpi/actions/workflows/lint-and-build.yml/badge.svg)](https://github.com/kleag/riffpi/actions/workflows/lint-and-build.yml)
[![PyPI](https://img.shields.io/pypi/v/riffpi)](https://pypi.org/project/riffpi/)
[![License: CERN-OHL-W-2.0](https://img.shields.io/badge/license-CERN--OHL--W--2.0-blue)](LICENSE.md)

RiffPi is the control daemon for **Kleag's MFX**, a DIY guitar multi-effect pedalboard built
around a Raspberry Pi, a [Pisound](https://blokas.io/pisound/) sound card, and
[Guitarix](https://guitarix.org/) as the effects engine. It reads the pedalboard's foot
switches, rotary encoders, keypad, joystick, and expression pedal, and turns them into MIDI
sent to Guitarix.

**Full documentation: <https://kleag.github.io/riffpi/>**

![The Kleag's MFX pedal](docs/images/img3.jpg)

## Features

- 4 foot switches with LEDs toggle Guitarix effects, and stay in sync if Guitarix changes state
  on its own (e.g. loading a preset).
- 4 rotary encoders send relative MIDI CC changes; the last one's button cycles preset banks A-D.
- A 4x4 keypad selects presets directly and doubles as mouse left/right click.
- A joystick moves the mouse pointer, for fine-tuning Guitarix's on-screen knobs, and its push
  acts as a middle click.
- An expression pedal sends a smoothed, continuous MIDI CC.
- Hardware design (KiCad) for the controller PCB, in [`kicad_board/`](kicad_board/).

## Quick start

```bash
pip install riffpi
riffpi install-service   # writes, enables, and starts a systemd --user service
```

See [Installation](https://kleag.github.io/riffpi/installation/) for the full Raspberry Pi
setup (I2C, `uinput` permissions, headless/no-login boot, WiFi power management), and
[Usage](https://kleag.github.io/riffpi/usage/) for what each control does and the full MIDI CC
mapping.

## Hardware

Wiring, MCP23017/ADS1115 pin maps, a block diagram, and the schematic/PCB renders are in
[Architecture](https://kleag.github.io/riffpi/architecture/). Hardware design source (KiCad 9)
is in [`kicad_board/`](kicad_board/).

## Development

```bash
uv build                       # or: python -m build
uvx ruff check src/            # lint
uvx twine check dist/*         # validate package metadata
.venv/bin/mkdocs serve         # preview the docs site locally
uvx bumpver update --minor     # bump the version (patch/minor/major)
```

CI (`.github/workflows/`) lints and builds the package on every push/PR, deploys the docs site
on changes to `docs/`, and publishes to PyPI on GitHub Release.

## License

Copyright Gaël de Chalendar, 2025-2026.

This project describes Open Hardware and is licensed under the CERN-OHL-W v2. You may
redistribute and modify it and make products using it under the terms of the
[CERN-OHL-W v2](https://cern.ch/cern-ohl) — see [`LICENSE.md`](LICENSE.md). It is distributed
WITHOUT ANY EXPRESS OR IMPLIED WARRANTY, INCLUDING OF MERCHANTABILITY, SATISFACTORY QUALITY AND
FITNESS FOR A PARTICULAR PURPOSE.

Source location: <https://github.com/kleag/riffpi>. As per CERN-OHL-W v2 section 4.1, should
you produce hardware based on these sources, you must keep the source location visible on the
external case of the pedal or other product you make using this documentation.
