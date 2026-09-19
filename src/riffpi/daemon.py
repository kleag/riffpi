#!/usr/bin/env python3
import logging
import queue
import subprocess
import threading
import time
from signal import pause

import adafruit_ads1x15.ads1115 as ADS
import board
import busio
import mido
from adafruit_mcp230xx.mcp23017 import MCP23017
from digitalio import Direction

from .expression_pedal import ExpressionPedal
from .joystick import Joystick
from .keypad import KeyPad
from .mcp_button import MCPButton
from .mcp_led import MCPLed
from .rotary_encoder import RotaryEncoder

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, force=True)

# --- CONFIGURATION ---
SWITCH_CC = 64  # MIDI CC number for effect toggles
ENCODER_CC_NUMBERS = [20, 21, 22, 23]  # MIDI CC for encoders

# Guitarix preset navigation settings
PRESET_BANK_CC = 32  # MIDI CC for preset bank selection
PRESET_CHANGE_CC = 0  # MIDI CC for preset change

# Keypad/Power LED (Keep original GPIO)
POWER_LED_PIN = 11

# MCP23017 1 Button/LED Map
BUTTON_PINS_MAP = [(1, 14), (1, 15), (1, 6), (1, 7)] # B6, B7, A6, A7
LED_PINS_MAP = [(1, 13), (1, 12), (1, 4), (1, 5)] # B5, B4, A4, A5

# --- MIDI/ENCODER LOGIC ---
effect_states = [False] * 4 # Global state for MIDI toggles

# Guitarix preset navigation
current_preset_bank = 0  # Current preset bank (0-3 for A-D)
current_preset = 0  # Current preset number within the bank (Program Change number)

# Index into `buttons` of the preset encoder's push button (the last encoder). `buttons`
# is [foot switches...] + [encoder buttons...], so this is only known once both are built;
# it's set in main() before any button-polling thread starts.
PRESET_ENCODER_INDEX = None

def send_cc(cc, value):
    msg = mido.Message('control_change', control=cc, value=value)
    midi_out.send(msg)

def set_preset_bank(bank_index):
    """Set the current preset bank (0-3 corresponding to A-D)"""
    global current_preset_bank
    if 0 <= bank_index <= 3:
        current_preset_bank = bank_index
        # Send MIDI messages to change bank
        reset()  # Reset all effects
        send_cc(PRESET_BANK_CC, bank_index)
        send_cc(PRESET_CHANGE_CC, 0)  # Select first preset in bank
        logger.info(f"Switched to preset bank {chr(ord('A') + bank_index)}")

def change_bank(delta):
    """Move to the next/previous preset bank, wrapping A-D (called when the preset
    encoder is rotated while its button is held)."""
    new_bank = (current_preset_bank + delta) % 4
    set_preset_bank(new_bank)

def change_preset(delta):
    """Move to the next/previous preset within the current bank (called when the
    preset encoder is rotated with its button released)."""
    global current_preset
    current_preset = max(0, min(127, current_preset + delta))
    reset()  # Reset all effects: presets define their own effect chain
    midi_out.send(mido.Message('program_change', program=current_preset))
    logger.info(f"Changing preset by {delta} -> preset {current_preset}")

# --- BUTTON HANDLERS ---
def handle_effect_toggle(idx):
    # The preset encoder's button only acts as a modifier for its rotation (see
    # RotaryEncoder.handle_rotation); a plain click with no rotation does nothing.
    if idx == PRESET_ENCODER_INDEX:
        return
    # Standard effect toggle behavior
    # logger.info(f"handle_effect_toggle {idx}")
    effect_states[idx] = not effect_states[idx]
    if leds[idx] is not None:
        leds[idx].value = effect_states[idx]
    send_cc(SWITCH_CC + idx, 127 if effect_states[idx] else 0)
    # logger.info(f"Button {idx} pressed. State: {effect_states[idx]}")


def reset():
    logger.info("reset")
    for i in range(len(effect_states)):
        effect_states[i] = False
        if leds[i] is not None:
            leds[i].value = False

# --- THREADS ---

def midi_input_thread():
    # logger.info("Listening for incoming MIDI messages...")
    for msg in midi_in:
        if msg.type == 'control_change':
            # logger.info(f"midi_input_thread received: {msg}")
            # Update Effect States (SWITCH_CC)
            if SWITCH_CC <= msg.control <= SWITCH_CC + 3:
                idx = msg.control - SWITCH_CC
                new_state = msg.value > 0

                # Only update if the state actually changed to avoid flickering
                if effect_states[idx] != new_state:
                    effect_states[idx] = new_state
                    if leds[idx] is not None:
                        leds[idx].value = new_state
                # logger.debug(f"Sync: LED {idx} set to {new_state} via MIDI")
            # Update Encoder CC Value if received externally
            if msg.control in ENCODER_CC_NUMBERS:
                for enc in encoders:
                    if enc.cc == msg.control:
                        enc.update_from_midi(msg.value)
                        break

def buttons_thread():
    while True:
        # MCP Button Scan
        for i, btn in enumerate(buttons):
            try:
                btn.check(i)
            except OSError as e:
                # Transient I2C bus glitch (e.g. "Remote I/O error"). Skip this button
                # this tick rather than letting the exception kill the whole thread.
                logger.warning(f"Button {i} I2C read failed: {e}")
        time.sleep(0.01)

# --- Main Thread Logic ---
def main_thread_loop():
    # logger.info("\n[Main Thread] Starting queue processor...")

    while True:
        while not task_queue.empty():
            try:
                func, args = task_queue.get(timeout=0.1)
                if func == "reset":
                    reset(*args)

                task_queue.task_done()
            except queue.Empty:
                # This happens if the queue is temporarily empty
                pass
        time.sleep(0.001)

def link_pipewire_ports():
    try:
        # Link Script -> Guitarix
        subprocess.run(
            ['pw-link', 'Midi-Bridge:RtMidiOut Client:(capture_0) KleagMFX', 'gx_head_amp:midi_in_1'],
            check=False,
        )
        # Link Guitarix -> Script
        subprocess.run(
            ['pw-link', 'gx_head_amp:midi_out_1', 'Midi-Bridge:RtMidiIn Client:(playback_0) KleagMFX'],
            check=False,
        )
        logger.info("PipeWire MIDI ports linked successfully.")
    except Exception as e:
        logger.error(f"Failed to link PipeWire ports: {e}")


def run():
    """Initialize hardware/MIDI and run the RiffPi daemon until interrupted."""
    global midi_out, midi_in, buttons, leds, encoders, task_queue, PRESET_ENCODER_INDEX

    # --- MIDI SETUP ---
    midi_out = mido.open_output('KleagMFX', virtual=True)
    midi_in = mido.open_input('KleagMFX', virtual=True)

    # --- HARDWARE INITIALIZATION ---
    i2c = busio.I2C(board.SCL, board.SDA)
    i2c_lock = threading.Lock()

    # ADS1115 for Joystick (kept as requested)
    ads = ADS.ADS1115(i2c)

    # MCP23017
    mcp1 = MCP23017(i2c, address=0x20)
    mcp2 = MCP23017(i2c, address=0x21)
    MCP_MAP = {1: mcp1, 2: mcp2}

    # Power LED
    power_led = mcp1.get_pin(POWER_LED_PIN)
    power_led.direction = Direction.OUTPUT
    power_led.value = True

    # Foot switches and their associated LED
    buttons = [MCPButton(MCP_MAP[mcp], pin) for mcp, pin in BUTTON_PINS_MAP]
    leds = [MCPLed(MCP_MAP[mcp], pin) for mcp, pin in LED_PINS_MAP]

    # Board label: as visible on physical pedalboard: mcp number and mcp pins map
    # RotaryEncoder4: 1st from left to right above : mcp n°2 clk B4=12 dt B3=11 sw B2=10
    # RotaryEncoder3: 2nd from left to right above : mcp n°2 clk B7=15 dt B6=14 sw B5=13
    # RotaryEncoder2: 3rd from left to right above : mcp n°1 clk A3=3  dt A2=2  sw A1=1
    # RotaryEncoder1: 4th from left to right above : mcp n°1 clk A0=0, dt B0=8, sw B1=9
    # --- ROTARY ENCODERS ---
    encoder_configs = [
        (mcp1, 0,   8,  9, "Encoder 0", ENCODER_CC_NUMBERS[0]), # CC 20
        (mcp1, 3,   2,  1, "Encoder 1", ENCODER_CC_NUMBERS[1]), # CC 21
        (mcp2, 15, 14, 13, "Encoder 2", ENCODER_CC_NUMBERS[2]), # CC 22
        (mcp2, 12, 11, 10, "Encoder 3", ENCODER_CC_NUMBERS[3]), # CC 23
    ]
    encoders = []
    for i, (mcp, clk_pin, dt_pin, sw_pin, name, cc) in enumerate(encoder_configs):
        # Make the last encoder (index 3) a preset encoder
        is_preset = (i == len(encoder_configs) - 1)
        encoder = RotaryEncoder(
            midi_out, mcp, name, clk_pin, dt_pin, sw_pin, cc, is_preset,
            on_preset_change=change_preset if is_preset else None,
            on_bank_change=change_bank if is_preset else None,
        )
        encoders.append(encoder)
        buttons.append(encoder.button)
        effect_states.append(False)
        leds.append(None)
        if is_preset:
            PRESET_ENCODER_INDEX = len(buttons) - 1

    for i, btn in enumerate(buttons):
        btn.when_pressed = handle_effect_toggle


    link_pipewire_ports()
    task_queue = queue.Queue()
    joystick = Joystick(ads, mcp1, lock=i2c_lock)
    keypad = KeyPad(task_queue, midi_out, mcp2)
    pedal = ExpressionPedal(midi_out, ads, lock=i2c_lock, channel=ADS.P2)

    threading.Thread(target=midi_input_thread, daemon=True).start()
    threading.Thread(target=buttons_thread, daemon=True).start()
    threading.Thread(target=joystick.poll_joystick, daemon=True).start()
    threading.Thread(target=keypad.keypad_thread, daemon=True).start()
    threading.Thread(target=pedal.poll, daemon=True).start()

    for encoder in encoders:
        threading.Thread(target=encoder.poll_thread, daemon=True).start()
    threading.Thread(target=main_thread_loop, daemon=True).start()

    logger.info("Kleag's Multi-effect daemon running.")
    try:
        pause()
    except KeyboardInterrupt:
        logger.info("Kleag's Multi-effect daemon terminating through keyboard interrupt.")


# === Main ===
if __name__ == "__main__":
    run()
