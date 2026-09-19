#!/usr/bin/env python3
import logging
import statistics
import threading
import time
from signal import pause

import adafruit_ads1x15.ads1115 as ADS
import board
import busio
import mido
from adafruit_ads1x15.analog_in import AnalogIn

# The actual voltages measured at the physical limits of the pedal
V_MIN = 0.006
V_MAX = 2.768
MIDI_CC_NUMBER = 24

logger = logging.getLogger(__name__)

class ExpressionPedal:
    def __init__(self, midi_out, ads: ADS.ADS1115, lock: threading.Lock, channel=ADS.P2, gain=1, v_ref=3.3):
        self.midi_out = midi_out
        # --- HARDWARE INITIALIZATION ---
        self.ads = ads
        self.lock = lock
        self.chan = AnalogIn(self.ads, channel)
        self.ads.data_rate = 860

        # 2. Configuration
        self.v_ref = v_ref
        self.ads.gain = gain  # Gain 1 = +/- 4.096V

        self._current_midi_val = -1
        self._running = False
        self.window_size = 5
        self.readings = [0] * self.window_size


    def poll(self):
        self._running = True
        while self._running:
            with self.lock:
                voltage = self.chan.voltage

            # Map voltage to 0-127 (MIDI Range)
            raw_percent = ((voltage - V_MIN) * 127) / (V_MAX - V_MIN)
            clamped = max(0, min(127, int(raw_percent)))

            # Smoothing
            self.readings.pop(0)
            self.readings.append(clamped)
            smoothed_val = int(statistics.median(self.readings))
            logger.debug(f"Pedal: {voltage};\t{clamped};\t{smoothed_val}")

            # Only send MIDI message if the value has actually changed
            if abs(smoothed_val - self._current_midi_val) >= 4:
                self._current_midi_val = smoothed_val
                self.send_midi(smoothed_val)

            time.sleep(0.01)

    def send_midi(self, value):
        msg = mido.Message('control_change', control=MIDI_CC_NUMBER, value=value)
        self.midi_out.send(msg)
        logger.debug(f"Pedal: Sent MIDI CC {MIDI_CC_NUMBER}: {value}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    i2c = busio.I2C(board.SCL, board.SDA)
    i2c_lock = threading.Lock()
    ads = ADS.ADS1115(i2c)
    # --- MIDI SETUP ---
    # This creates a virtual MIDI port that shows up in patchage/qjackctl
    midi_out = mido.open_output('ExpressionPedalPort', virtual=True)
    logger.info("Virtual MIDI port 'ExpressionPedalPort' created.")

    pedal = ExpressionPedal(midi_out, ads, i2c_lock)

    t = threading.Thread(target=pedal.poll, daemon=True)
    t.start()

    logger.info("ExpressionPedal to MIDI running. Press Ctrl+C to stop.")
    try:
        pause()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
