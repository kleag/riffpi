#!/usr/bin/env python3
import logging

from adafruit_mcp230xx.mcp23017 import MCP23017
from digitalio import Direction, Pull

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

class MCPButton:
    """ MCP23017 Button """
    def __init__(self, mcp: MCP23017, pin: int):
        # logger.info(f"MCPButton {pin}")
        self.pin = mcp.get_pin(pin)
        self.pin.direction = Direction.INPUT
        self.pin.pull = Pull.UP
        self.last_state = not self.pin.value # Active Low
        self.when_pressed = None

    def check(self, idx: int):
        current_state = not self.pin.value
        # logger.info(f"MCPButton.check {idx}, {self.when_pressed}: {current_state} / {self.last_state}")
        if current_state and not self.last_state:
            if self.when_pressed:
                self.when_pressed(idx)
        self.last_state = current_state

