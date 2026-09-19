#!/usr/bin/env python3
import logging
import queue
import threading
import time
from signal import pause
from typing import List

import board
import busio
import mido
import uinput
from adafruit_mcp230xx.mcp23017 import MCP23017
from digitalio import Direction, Pull

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# --- CONFIGURATION ---

KEYPAD_ROW_PINS = [0, 1, 2, 3]
KEYPAD_COL_PINS = [4, 5, 6, 7]

# Max delay (seconds) between digit key presses to form a multi-digit preset
DIGIT_SEQUENCE_TIMEOUT = 0.4

class KeyPad:
    keypad_map = [
        ['1', '2', '3', 'A'],
        ['4', '5', '6', 'B'],
        ['7', '8', '9', 'C'],
        ['*', '0', '#', 'D']
    ]

    def __init__(
        self,
        task_queue: queue.Queue,
        midi_out,
        mcp: MCP23017,
        row_pins: List[int] = KEYPAD_ROW_PINS,
        col_pins: List[int] = KEYPAD_COL_PINS,
    ):
        self.task_queue = task_queue
        self.last_key = None
        self.midi_out = midi_out
        self.mcp = mcp
        self.digit_buffer = ""
        self.last_digit_time = 0.0
        self.pending_preset = False
        self.left_state = False
        self.right_state = False

        # --- VIRTUAL MOUSE SETUP (buttons only) ---
        try:
            self.mouse = uinput.Device([
                uinput.BTN_LEFT,
                uinput.BTN_RIGHT,
            ])
        except Exception as e:
            logger.error(f"KeyPad uinput init failed: {e}")
            self.mouse = None

        self.kp_rows = [self.mcp.get_pin(i) for i in row_pins]
        self.kp_cols = [self.mcp.get_pin(i) for i in col_pins]

        for row in self.kp_rows:
            row.direction = Direction.OUTPUT
            row.value = True  # default HIGH

        for col in self.kp_cols:
            col.direction = Direction.INPUT
            col.pull = Pull.UP  # enable pull-ups

    def scan_keypad(self):
        for row_idx, row in enumerate(self.kp_rows):
            row.value = False  # Set current row to LOW
            for col_idx, col in enumerate(self.kp_cols):
                if not col.value:  # If column is also LOW, key is pressed
                    char = KeyPad.keypad_map[row_idx][col_idx]
                    row.value = True  # Cleanup: Reset row before returning
                    return char
            row.value = True  # Reset row for next iteration
        return None

    def set_bank(self, value: int):
        # logger.info(f"KeyPad.set_bank {value}")
        self.task_queue.put(("reset", []))
        self.midi_out.send(mido.Message('control_change', control=0, value=2))
        self.midi_out.send(mido.Message('control_change', control=32, value=value))
        self.midi_out.send(mido.Message('program_change', program=0))

    def set_preset(self, value: int):
        # logger.info(f"KeyPad.set_preset {value}")
        self.task_queue.put(("reset", []))
        self.midi_out.send(mido.Message('program_change', program=value))

    def keypad_thread(self):
        while True:
            # Keypad Scan
            key = self.scan_keypad()
            now = time.monotonic()

            # Commit pending preset if timeout expired
            if self.pending_preset and (now - self.last_digit_time) > DIGIT_SEQUENCE_TIMEOUT:
                try:
                    preset = int(self.digit_buffer)
                    self.set_preset(preset)
                finally:
                    self.digit_buffer = ""
                    self.pending_preset = False

            if key and key != self.last_key:
                # logger.info(f"Key pressed: {key}")
                if key in 'ABCD':
                    self.digit_buffer = ""
                    self.pending_preset = False
                    self.set_bank(ord(key) - ord('A'))
                elif key in '0123456789':
                    if (now - self.last_digit_time) <= DIGIT_SEQUENCE_TIMEOUT:
                        self.digit_buffer += key
                    else:
                        self.digit_buffer = key

                    self.last_digit_time = now
                    self.pending_preset = True
                elif key == '*' and self.mouse:
                    if not self.left_state:
                        logger.debug("Left button pressed")
                        self.mouse.emit(uinput.BTN_LEFT, 1)
                        self.mouse.syn() # Ensure the event is flushed to the OS immediately
                        self.left_state = True
                elif key == '#' and self.mouse:
                    if not self.right_state:
                        logger.debug("Right button pressed")
                        self.mouse.emit(uinput.BTN_RIGHT, 1)
                        self.mouse.syn() # Ensure the event is flushed to the OS immediately
                        self.right_state = True
                self.last_key = key

            elif key != '*' and self.left_state:
                logger.debug("Left button released")
                self.mouse.emit(uinput.BTN_LEFT, 0)
                self.mouse.syn()
                self.left_state = False

            elif key != '#' and self.right_state:
                logger.debug("Right button released")
                self.mouse.emit(uinput.BTN_RIGHT, 0)
                self.mouse.syn()
                self.right_state = False

            elif key is None:
                self.last_key = None

            time.sleep(0.01)


# === Main ===
if __name__ == "__main__":
    i2c = busio.I2C(board.SCL, board.SDA)
    mcp = MCP23017(i2c, address=0x21)
    # --- MIDI SETUP ---
    midi_out = mido.open_output('KleagMFX', virtual=True)
    task_queue = queue.Queue()
    keypad = KeyPad(task_queue, midi_out, mcp)
    threading.Thread(target=keypad.keypad_thread, daemon=True).start()

    logger.info("KeyPad daemon running.")
    pause()
