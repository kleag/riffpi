#!/usr/bin/env python3
from adafruit_mcp230xx.mcp23017 import MCP23017
from digitalio import Direction


class MCPLed:
    """ MCP23017 LED """
    def __init__(self, mcp: MCP23017, pin: int):
        self.pin = mcp.get_pin(pin)
        self.pin.direction = Direction.OUTPUT
        self._value = False
        self.value = False

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, state):
        self._value = state
        self.pin.value = state

