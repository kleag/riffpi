#!/usr/bin/env python3
import logging
import time
from signal import pause

import mido
from adafruit_mcp230xx.mcp23017 import MCP23017
from digitalio import Direction, Pull

from .mcp_button import MCPButton

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---

ENCODER_STEP = 5  # Value change per encoder tick (approx. 5% of 127)
SWITCH_CC = 64  # MIDI CC number for effect toggles

class RotaryEncoder:
    # 4. Define Valid Transitions (Standard Quadrature Sequence)
    # Clockwise (CW) steps:
    # 00 -> 10 (0x2)
    # 10 -> 11 (0xB)
    # 11 -> 01 (0x7)
    # 01 -> 00 (0x4)
    CW_transitions = {0b0010, 0b1011, 0b1101, 0b0100} # Set of 4-bit transition keys

    # Counter-Clockwise (CCW) steps (Reversed Sequence):
    # 00 -> 01 (0x1)
    # 01 -> 11 (0x7) -> NOTE: 0x7 (1101) is CCW, 0x7 (0111) is CW
    # Let's list the CCW sequences explicitly:
    # 00 -> 01 (0x1)
    # 01 -> 11 (0x7)
    # 11 -> 10 (0xE)
    # 10 -> 00 (0x8)
    CCW_transitions = {0b0001, 0b0111, 0b1110, 0b1000}

    def __init__(
        self,
        midi_out,
        mcp: MCP23017,
        name: str,
        clk_pin: int,
        dt_pin: int,
        sw_pin: int,
        cc: int,
        is_preset_encoder: bool = False,
    ):
        logger.info(f"RotaryEncoder {name}, clk: {clk_pin}, dt: {dt_pin}, sw: {sw_pin}, cc: {cc}")
        self.midi_out = midi_out
        self.clk = mcp.get_pin(clk_pin)
        self.dt = mcp.get_pin(dt_pin)
        initial_clk = self.clk.value
        initial_dt = self.dt.value
        for pin in (self.clk, self.dt):
            pin.direction = Direction.INPUT
            pin.pull = Pull.UP
        self.name = name,
        self.cc = cc
        # self.sw = sw
        # self.last_clk = self.clk.value
        self.last_state = (initial_clk << 1) | initial_dt
        # self.last_sw = sw.value
        self.midi_value = SWITCH_CC
        self.button = MCPButton(mcp, sw_pin)
        self.is_preset_encoder = is_preset_encoder
        self.button.when_pressed = self.button_pressed
        self.send_cc(self.midi_value)

    def button_pressed(self):
        logger.debug(f"RotaryEncoder {self.name} button_pressed")


    def preset_button_pressed(self):
        """Special handler for preset bank switching"""
        logger.info(f"Preset encoder {self.name} button pressed - switching bank")
        # This will be handled by the main program
        # We'll send a message to indicate the button was pressed
        pass


    def update_from_midi(self, value):
        """External sync: Updates the internal value without sending a MIDI msg."""
        if 0 <= value <= 127:
            self.midi_value = value
            logger.debug(f"{self.name} synced to {value}")

    def read_encoder_state_machine(self):

        # 1. Read Current State (2-bit value: (clk << 1) | dt)
        current_clk = int(self.clk.value)
        # print(type(current_clk), current_clk)
        current_dt = int(self.dt.value)
        current_state = (current_clk << 1) | current_dt # e.g., 00, 01, 10, or 11

        # 2. Check if the state has changed
        if current_state != self.last_state:

            # 3. Create a 4-bit transition key: (last_state << 2) | current_state
            # This key defines the exact transition, e.g., 00 -> 10, or 10 -> 11
            transition = (self.last_state << 2) | current_state

            # 5. Check if the transition is valid and update
            if transition in RotaryEncoder.CW_transitions:
                # logger.debug(f"Encoder {self.name} Rotated → (clockwise)")
                self.last_state = current_state # Update state after a valid step
                direction = 1
                # logger.info(f"{encoder['name']} turned {direction}, send to {encoder['cc']}")
                self.increment_cc_value(direction)

            elif transition in RotaryEncoder.CCW_transitions:
                # logger.debug(f"Encoder {self.name} Rotated → (counterclockwise)")
                self.last_state = current_state # Update state after a valid step
                direction = -1
                # logger.debug(f"{encoder['name']} turned {direction}, send to {encoder['cc']}")
                self.increment_cc_value(direction)

            # 6. Optional: If the transition is invalid (i.e., due to bounce/noise),
            #    we generally ignore it and wait for a valid state.
            #    However, if we are in a state not part of the sequence,
            #    we might reset the state to catch up. For simplicity, we only
            #    update the state on a valid transition.
            else:
                # 5. CATCH-UP LOGIC: If the transition is INVALID (due to bounce or skipped steps),
                #    we force the last_state to the current_state.
                #    This ignores the current invalid movement but prepares the encoder
                #    to detect the next valid step from the new physical position.
                # logger.debug(f"Encoder {encoder['name']} state corrected (Invalid transition: {bin(transition)})")
                self.last_state = current_state
            # The key is to only update last_state *after* a valid transition has completed.

    def send_cc(self, value):
        # logger.info(f"RotaryEncoder.send_cc {self.name}: {self.cc}, {value}")
        msg = mido.Message('control_change', control=self.cc, value=value)
        self.midi_out.send(msg)

    def increment_cc_value(self, direction):
        """Adjusts the MIDI CC value for an encoder incrementally."""
        current_value = self.midi_value
        # Adjust by ENCODER_STEP, then clamp
        new_value = max(0, min(127, current_value + direction * ENCODER_STEP))
        if new_value != current_value:
            self.midi_value = new_value
            self.send_cc(new_value)
            # logger.debug(f"{self.name} CC {self.cc} adjusted to {new_value}")

    def poll_thread(self):
        while True:
            try:
                self.read_encoder_state_machine()
            except OSError as e:
                # Transient I2C bus glitch (e.g. "Remote I/O error"). Skip this tick
                # rather than letting the exception kill the thread for the process's
                # remaining lifetime.
                logger.warning(f"RotaryEncoder {self.name} I2C read failed: {e}")
            time.sleep(0.001)


# === Main ===
if __name__ == "__main__":
    import threading

    import board
    import busio

    i2c = busio.I2C(board.SCL, board.SDA)
    mcp = MCP23017(i2c, address=0x20)
    # --- MIDI SETUP ---
    midi_out = mido.open_output('KleagMFX', virtual=True)
    encoder = RotaryEncoder(midi_out, mcp, "Encoder 0", 9, 8, 0, 20)
    threading.Thread(target=encoder.poll_thread, daemon=True).start()

    logger.info("RotaryEncoder daemon running.")
    pause()
