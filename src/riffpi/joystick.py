#!/usr/bin/env python3
import logging
import math
import statistics
import threading
import time
from signal import pause

import adafruit_ads1x15.ads1115 as ADS
import board
import busio
import uinput
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_mcp230xx.mcp23017 import MCP23017
from digitalio import Direction, Pull
from rich.console import Console

logger = logging.getLogger(__name__)


class Joystick:
    # --- CONFIGURATION ---
    # Maximum mouse speed (pixels/s) reached only at full deflection (|x|/|y| == 1.0).
    SENSITIVITY = 30.0
    # Fraction of travel (0.0-1.0) around center treated as "not moved". Noise is filtered
    # separately (SMOOTHING_WINDOW), so this only needs to absorb residual jitter.
    DEAD_ZONE = 0.02
    # Exponent applied to the (post-dead-zone) normalized deflection before scaling by
    # SENSITIVITY. Must be > 1: with an exponent < 1 the curve has infinite slope at 0, so
    # speed jumps immediately once past the dead zone (the "dead then jumpy" feel this
    # replaces). >1 makes the slope start at 0 and ramp up smoothly, so small deflections
    # give fine/slow motion (useful for nudging a Guitarix knob) and only large deflections
    # approach SENSITIVITY. Raise it further (e.g. 3.0-4.0) for even finer low-end control.
    POWER_CURVE = 2.5
    # Number of raw voltage samples averaged (median) per axis to smooth out ADC/electrical
    # noise from the joystick's low-cost potentiometers before it reaches the dead zone/curve.
    SMOOTHING_WINDOW = 5
    LOOP_DELAY = 0.01  # General loop delay (seconds)

    def __init__(self, ads: ADS.ADS1115, mcp: MCP23017, lock: threading.Lock, debug: bool = False):
        self.debug = debug
        # --- HARDWARE INITIALIZATION ---
        self.ads = ads
        self.lock = lock
        # Use P0 and P1 for Joystick X and Y
        self.joystick_x_axis = AnalogIn(ads, ADS.P0)
        self.joystick_y_axis = AnalogIn(ads, ADS.P1)


        # --- JOYSTICK/MOUSE SETUP (retained ADS1115 usage) ---
        events = (uinput.REL_X, uinput.REL_Y, uinput.BTN_LEFT, uinput.BTN_RIGHT, uinput.BTN_MIDDLE)
        try:
            self.device = uinput.Device(events)
        except Exception as e:
            logger.error(
                "UInput device creation failed. Check permissions (sudo or your user "
                f"in the input group setup with udev). Error: {e}"
            )
            exit(1)

        self.joystick_sw = mcp.get_pin(10)  # B2
        self.joystick_sw.direction = Direction.INPUT
        self.joystick_sw.pull = Pull.UP
        self.last_switch_state = True # True = not pressed
        self.last_x = 0
        self.last_y = 0
        self.spike_count_x = 0
        self.spike_count_y = 0
        self.console = Console()

        self.x_readings = [0.0] * Joystick.SMOOTHING_WINDOW
        self.y_readings = [0.0] * Joystick.SMOOTHING_WINDOW
        self.x_center, self.y_center = self.calibrate_center()

    def calibrate_center(self, samples: int = 50, delay: float = 0.01):
        """Measure the at-rest center voltage per axis instead of assuming a fixed value.

        Assumes the joystick is untouched (spring-centered) when this runs, i.e. at
        startup before the poll loop begins. Uses the median to stay robust if it's
        bumped once during the sampling window.
        """
        x_samples = []
        y_samples = []
        for _ in range(samples):
            with self.lock:
                x_samples.append(self.joystick_x_axis.voltage)
                y_samples.append(self.joystick_y_axis.voltage)
            time.sleep(delay)
        x_center = statistics.median(x_samples)
        y_center = statistics.median(y_samples)
        logger.info(f"Joystick calibrated center: x={x_center:.3f}V, y={y_center:.3f}V")
        return x_center, y_center

    def read_joystick(self):
        """Return normalized X, Y values in range -1.0 .. +1.0 using ADS1115."""
        with self.lock:
            raw_x = self.joystick_x_axis.voltage
            raw_y = self.joystick_y_axis.voltage

        self.x_readings.pop(0)
        self.x_readings.append(raw_x)
        self.y_readings.pop(0)
        self.y_readings.append(raw_y)
        smoothed_x = statistics.median(self.x_readings)
        smoothed_y = statistics.median(self.y_readings)

        x = (smoothed_x - self.x_center) / self.x_center
        y = (smoothed_y - self.y_center) / self.y_center
        return max(-1, min(1, x)), max(-1, min(1, y))

    def calculate_speed(self, x, y):
        # --- 1. Glitch Guard Logic ---
        # If the reading is exactly 1.0 (or -1.0) and we were just at 0
        if abs(x) > 0.99 and abs(self.last_x) < 0.1:
            self.spike_count_x += 1
            if self.spike_count_x < 2: # Ignore the first frame of a max-value spike
                x = 0
        else:
            self.spike_count_x = 0

        if abs(y) > 0.99 and abs(self.last_y) < 0.1:
            self.spike_count_y += 1
            if self.spike_count_y < 2:
                y = 0
        else:
            self.spike_count_y = 0

        self.last_x, self.last_y = x, y

        # --- 2. Axial Dead Zone Logic ---
        # X Axis
        if abs(x) < Joystick.DEAD_ZONE:
            dx = 0
        else:
            norm_x = (abs(x) - Joystick.DEAD_ZONE) / (1.0 - Joystick.DEAD_ZONE)
            dx = math.pow(norm_x, Joystick.POWER_CURVE) * math.copysign(Joystick.SENSITIVITY, x)

        # Y Axis
        if abs(y) < Joystick.DEAD_ZONE:
            dy = 0
        else:
            norm_y = (abs(y) - Joystick.DEAD_ZONE) / (1.0 - Joystick.DEAD_ZONE)
            dy = math.pow(norm_y, Joystick.POWER_CURVE) * math.copysign(Joystick.SENSITIVITY, y)

        return dx, dy

    def poll_joystick(self):
        while True:
            try:
                # 1. Joystick Analog Control (Reads from ADS1115)
                x, y = self.read_joystick()
                # logger.debug(f"joystick {x},{y}")
                dx, dy = self.calculate_speed(x, y)
                if dx != 0 or dy != 0:
                    # logger.debug(f"joystick move: {dx},{dy}")
                    try:
                        self.device.emit(uinput.REL_X, int(-dx))
                        self.device.emit(uinput.REL_Y, int(-dy))
                    except NameError as e: # Handle case where uinput device failed to initialize
                        logger.warn(f"Joystick.poll_joystick uinput failure: {e}")

                # 2. Joystick Button (Reads from MCP23017)
                switch_state = self.joystick_sw.value  # True = not pressed
                if switch_state != self.last_switch_state:
                    uinput_state = 1 if not switch_state else 0
                    # logger.debug(f"joystick button new state: {uinput_state}")
                    try:
                        self.device.emit(uinput.BTN_MIDDLE, uinput_state)
                    except NameError as e:
                        logger.error(f"Name error in joystick button: {e}")

                self.last_switch_state = switch_state
                if self.debug:
                    status_text = (
                        f"[bold blue]X:[/bold blue] {self.joystick_x_axis.voltage:+5.2f}V "
                        f"({x:+5.2f}) [dim]dx={dx:+6.2f}[/dim] | "
                        f"[bold magenta]Y:[/bold magenta] {self.joystick_y_axis.voltage:+5.2f}V "
                        f"({y:+5.2f}) [dim]dy={dy:+6.2f}[/dim] | "
                        f"[bold yellow]Switch:[/bold yellow] "
                        f"{'Released' if switch_state else 'Pressed'}"
                    )
                    self.console.print(status_text, end="\r")
            except OSError as e:
                # Transient I2C bus glitch (e.g. "Remote I/O error"). Skip this tick
                # rather than letting the exception kill the thread.
                logger.warning(f"Joystick I2C read failed: {e}")
            time.sleep(Joystick.LOOP_DELAY)


# === Main ===
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
        # --- HARDWARE INITIALIZATION ---
    i2c = busio.I2C(board.SCL, board.SDA)
    i2c_lock = threading.Lock()

    # ADS1115 for Joystick (kept as requested)
    ads = ADS.ADS1115(i2c)

    mcp = MCP23017(i2c, address=0x20)

    joystick = Joystick(ads, mcp, lock=i2c_lock, debug=True)
    threading.Thread(target=joystick.poll_joystick, daemon=True).start()

    logger.info("Joystick daemon running.")
    pause()
