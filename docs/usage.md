# Usage

Once `riffpi` is running (see [Installation](installation.md)) and linked to Guitarix over
PipeWire MIDI, the pedalboard's controls behave as follows.

## Foot switches

4 foot switches with LEDs toggle Guitarix effects on/off. Pressing a switch flips its state,
lights/dims its LED, and sends a MIDI CC. If Guitarix reports a state change back (e.g. after
loading a preset), the LED updates to match automatically.

| Foot switch | MIDI CC |
|---|---|
| 1 | 64 |
| 2 | 65 |
| 3 | 66 |
| 4 | 67 |

## Rotary encoders

The first 3 rotary encoders send relative MIDI CC changes as they're turned — each detent moves
its CC value by ±5 (clamped to 0-127). This is meant for continuous Guitarix parameters (gain,
tone, etc.) rather than on/off effects.

| Encoder | MIDI CC |
|---|---|
| 1 | 20 |
| 2 | 21 |
| 3 | 22 |

The **4th (preset) encoder** works differently: turning it moves to the next/previous preset
within the current bank (a Program Change, one per detent). Its push button instead cycles
through Guitarix preset banks **A → B → C → D → A...** (sends CC32 = bank index, then a
bank-select Program Change). The other three encoders' buttons behave like extra foot switches.

## Keypad

A 4x4 matrix keypad selects presets directly and doubles as mouse buttons:

- **A / B / C / D** — select preset bank A-D immediately (same effect as cycling with the last
  encoder's button, but direct).
- **0-9** — type a preset number. Digits typed within 0.4s of each other accumulate (e.g. `1`
  then `2` within the window selects preset 12); after 0.4s of no further digits, the number is
  sent as a Program Change and the buffer resets.
- **\*** — virtual mouse left click (held down while the key is held).
- **#** — virtual mouse right click (held down while the key is held).

Selecting a bank or preset resets all foot-switch effect states/LEDs, since Guitarix presets
define their own effect chain.

## Joystick

The analog joystick moves the mouse pointer — useful for dragging Guitarix's on-screen knobs to
fine-tune a parameter without leaving the pedalboard. Pushing the joystick in also acts as a
middle-click.

Cursor speed ramps up smoothly from the center: small deflections move the pointer slowly (for
precise knob nudges), and only a large deflection reaches full speed. Raw readings are smoothed
to filter out electrical noise from the joystick's potentiometers, and the center position is
measured automatically each time `riffpi` starts (so it doesn't need to be physically centered
with high precision). If the feel still isn't right for your hardware, `SENSITIVITY`,
`DEAD_ZONE`, `POWER_CURVE`, and `SMOOTHING_WINDOW` at the top of `riffpi/joystick.py` are the
constants to tune — see the comments there for what each one does.

## Expression pedal

The expression pedal sends MIDI CC 24, mapped from its measured voltage range and smoothed with
a rolling median filter to avoid jitter.

## MIDI CC reference

| Control | MIDI CC(s) |
|---|---|
| Foot switches 1-4 | 64-67 |
| Rotary encoders 1-3 | 20-22 |
| Preset encoder: preset change (turn) | Program Change |
| Preset encoder: bank change (click) | 32 (bank), Program Change (preset within bank) |
| Expression pedal | 24 |
