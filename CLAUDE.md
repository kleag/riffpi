# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

RiffPi (PyPI/import name `riffpi`; the GitHub repo itself stays `kleag/kleagmfx`) is a DIY guitar
multi-effect foot controller built around a Raspberry Pi 5 + Pisound sound card, running Guitarix
as the effects engine. This repo holds:

- `src/riffpi/`: the installable Python package — the control daemon that reads the physical
  controls (foot switches, rotary encoders, keypad, joystick, expression pedal) and drives
  Guitarix over a virtual MIDI port.
- Root-level `*_test.py` / `*_int.py` files: standalone manual/legacy hardware scripts, **not**
  part of the installed package (see Testing and Architecture below).
- KiCad hardware design files for the controller PCB (`kicad_board/`).
- MkDocs documentation source (`docs/`), published to GitHub Pages.

The hardware talks to the Pi over I2C: two MCP23017 GPIO expanders (`0x20`, `0x21`) for buttons/
LEDs/encoders/keypad, and an ADS1115 ADC for the analog joystick and expression pedal. Full
wiring/pin maps live in `docs/architecture.md`; Raspberry Pi OS setup (I2C enablement, `uinput`
permissions, systemd service, etc.) is in `docs/installation.md`.

## Environment & running

- Python >=3.11, packaged with `hatchling` (`[build-system]` in `pyproject.toml`). Build with
  `python -m build` or `uv build`; install locally with `pip install -e .`.
- Hardware-dependent libraries (`board`, `busio`, `digitalio`, `adafruit_*`, `gpiozero`, `uinput`,
  ...) only work on an actual Raspberry Pi with I2C enabled and the user in the `input` group.
  **None of this code can be run or imported on a non-Pi dev machine** — Blinka (`board`/`busio`)
  actively probes for real hardware on import and raises if it doesn't find a supported board.
  Reason about the package by reading; verify changes with `python -m py_compile` and `ruff
  check src/`, not by importing/running it.
- Entry point: the `riffpi` console script (`riffpi.cli:main`, installed via
  `[project.scripts]`), an argparse dispatcher over three subcommands — `run` (default when no
  subcommand is given), `install-service`, `uninstall-service`. `riffpi run` calls
  `riffpi.daemon.run()`, which opens a virtual ALSA/JACK MIDI port named `KleagMFX` via `mido`,
  links it to Guitarix (`gx_head_amp`) through PipeWire (`pw-link`), then spawns one thread per
  input device (buttons, joystick, keypad, expression pedal, each rotary encoder) plus a
  MIDI-input listener thread that keeps LED/encoder state in sync when Guitarix itself changes a
  CC value.
- `riffpi install-service` / `riffpi uninstall-service` (implemented in `riffpi/service.py`)
  write/remove `~/.config/systemd/user/riffpi.service` and enable/disable it via `systemctl
  --user`. `pip install` never does this on its own — it's a deliberate, separate opt-in step;
  don't wire service installation into packaging/install hooks. See `docs/installation.md` for
  the full flow and PipeWire/udev/wifi power-management setup.

## Testing

There is no pytest/unittest suite. Root-level files named `*_test.py` (and `test_int.py`) are
standalone manual exercise scripts for a single piece of hardware — run directly on the Pi
(`python3 rotary_encoder_test.py`) with real hardware attached, and verified by watching printed
output / physical LEDs, not by assertions. They are **not** part of the `src/riffpi` package and
aren't shipped in the wheel/sdist. When changing a driver module, prefer updating or running its
matching `*_test.py` script over trying to add automated tests.

CI (`.github/workflows/lint-and-build.yml`) runs `ruff check src/` plus `python -m build` +
`twine check dist/*` on every push/PR — lint and packaging validation only. It cannot actually
import or run `riffpi` (see the Blinka caveat above), so this is the practical ceiling for
automated verification without a self-hosted Pi runner.

## Docs site & release

- `docs/` is an MkDocs (Material theme) site, configured by `mkdocs.yml`.
  `.github/workflows/docs.yml` runs `mkdocs gh-deploy --force`, but only on pushes to `main` that
  touch `docs/`, `mkdocs.yml`, or `README.md`.
- `.github/workflows/release.yml` builds and publishes to PyPI on GitHub Release, via Trusted
  Publishing (OIDC) — no stored token. Requires the `riffpi` PyPI project to have this repo
  registered as a trusted publisher (a one-time manual step on pypi.org).

## Code architecture

### Two parallel implementations per device: package vs. root-level register-level scripts

Most physical inputs have **two independent implementations**:

- The production version, in `src/riffpi/` (imported by `riffpi.daemon`), built on the Adafruit
  CircuitPython stack (`adafruit_mcp230xx`, `digitalio.Direction`/`Pull`, `busio.I2C`) —
  `rotary_encoder.py`, `keypad.py`, `joystick.py`, `expression_pedal.py`, `mcp_button.py`,
  `mcp_led.py`.
- Root-level `*_int.py` scripts (e.g. `rotary_encoder_int.py`, `multieffect_int.py`,
  `test_int.py`) that talk to the MCP23017 directly over `smbus2`/`lgpio` register writes and use
  hardware interrupts (`GPINTEN`, `lgpio.callback` on falling edges) instead of polling. These are
  an alternate/experimental lower-latency approach, not wired into the main daemon and not part
  of the installed package.

When asked to fix or extend a device driver, check whether the change belongs in the
`src/riffpi/` version, the root-level `_int` register-level version, or both — they duplicate
logic independently and are **not** kept in sync automatically.

### Control flow in `riffpi/daemon.py`

- `main()` does all hardware/MIDI init (previously module-level code in the pre-packaging
  `multieffect.py`) then spawns the worker threads; module-level functions (`handle_effect_toggle`,
  `midi_input_thread`, `buttons_thread`, `main_thread_loop`, `send_cc`, ...) reach the objects
  `main()` creates (`midi_out`, `midi_in`, `buttons`, `leds`, `encoders`, `task_queue`,
  `PRESET_ENCODER_INDEX`) via `global`, matching the module's original flat-script style rather
  than passing them around explicitly — keep that pattern if you touch this file rather than
  introducing a class/config-object refactor.
- Global state: `effect_states` (bool per foot switch + one slot per encoder's button) and
  `current_preset_bank` are shared across threads with no lock beyond the implicit GIL for simple
  list/int mutation; the one place true cross-thread coordination happens is `task_queue`
  (a `queue.Queue` drained by `main_thread_loop`, currently only used for the `"reset"` action
  queued from `keypad.py`).
- `i2c_lock` (a `threading.Lock`) guards ADS1115 reads shared between `Joystick` and
  `ExpressionPedal`, since both poll the same `ads` instance from different threads.
- Foot switch buttons and each `RotaryEncoder`'s built-in push button all route through the same
  `handle_effect_toggle(idx)` callback, where `idx` is the position in the `buttons` list
  (`[4 foot switches] + [4 encoder buttons]`, in that order). `PRESET_ENCODER_INDEX` is computed
  in `main()` as the buttons-list position of the **last encoder's** button (not a hardcoded
  literal — it was hardcoded to `3` at one point, which actually pointed at the 4th foot switch
  instead; don't reintroduce that). That button is special-cased to cycle Guitarix preset banks
  A-D instead of toggling an effect.
- MIDI CC numbers are the integration contract with Guitarix: `SWITCH_CC=64` (+idx per foot
  switch), `ENCODER_CC_NUMBERS=[20,21,22,23]`, `PRESET_BANK_CC=32`, `PRESET_CHANGE_CC=0`,
  expression pedal `MIDI_CC_NUMBER=24`. The `midi_input_thread` listens on the same virtual port
  for CC echoes from Guitarix and updates local LED/encoder state to stay in sync when a preset
  change alters effect state externally. Full mapping table: `docs/usage.md`.
- Physical pin maps for buttons/LEDs/encoders are hardcoded per-MCP as `(mcp_number, pin)` tuples
  at the top of `daemon.py` — cross-reference against the pinout comments above
  `encoder_configs` (which board is "1st/2nd/3rd/4th from left to right") and the tables in
  `docs/architecture.md` before changing wiring.

### Device driver modules (`src/riffpi/`)

Each driver is a small class taking its shared hardware handles (`mcp`, `ads`, `i2c_lock`,
`midi_out`) in its constructor and exposing a blocking `poll()`/`poll_thread()`/`*_thread()`
method meant to be run in its own daemon thread; each also has an `if __name__ == "__main__"`
block for standalone hardware testing of just that module (only usable when run from a checkout,
not through the installed console script).

- `rotary_encoder.py`: quadrature decoding via a transition lookup table (`CW_transitions`/
  `CCW_transitions` — 4-bit keys of `(last_state<<2)|current_state`), sends relative MIDI CC deltas.
- `keypad.py`: 4x4 matrix scan; digits accumulate into a preset number with a
  `DIGIT_SEQUENCE_TIMEOUT` debounce window, `A`-`D` select preset banks, `*`/`#` emit virtual
  mouse left/right clicks via `uinput`.
- `joystick.py`: reads the ADS1115 (`AnalogIn`), median-smooths raw voltage per axis
  (`SMOOTHING_WINDOW`), auto-calibrates center voltage at startup (`calibrate_center()`), and
  shapes deflection into relative `uinput` mouse motion via a dead zone (`DEAD_ZONE`) + power
  curve (`POWER_CURVE`, must stay `>1` — a curve `<1` has infinite slope at zero and produces a
  "dead then jumpy" feel; see the comments on the class constants).
- `expression_pedal.py`: reads the ADS1115, median-smooths readings, sends MIDI CC.
- `mcp_button.py` / `mcp_led.py`: thin per-pin wrappers around an MCP23017 pin for debounced
  button state (`when_pressed` callback) and LED output.
