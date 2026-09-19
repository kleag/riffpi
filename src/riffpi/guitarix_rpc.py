#!/usr/bin/env python3
"""Minimal client for Guitarix's JSON-RPC control port (`guitarix -p PORT`).

Guitarix's JSON-RPC protocol is plain newline-terminated JSON over a raw TCP socket (not
HTTP). This client only wraps the handful of read-only calls RiffPi needs to look up how
many presets exist in the currently loaded bank:

- `get_parameter(["system.current_bank"])` -> current bank name
- `get_parameter(["system.current_preset"])` -> current preset name
- `get_bank([bank_name])` -> `{"presets": [...]}, ordered the same way as MIDI Program
  Change numbers within that bank
"""
import json
import logging
import socket
import threading
import time

logger = logging.getLogger(__name__)

# After a connection failure, don't retry for this long — callers (encoder rotation) may
# invoke this many times a second, and a dead/never-started RPC server would otherwise
# make every single call pay a full connect timeout.
RECONNECT_BACKOFF = 5.0


class GuitarixRPCError(Exception):
    """Raised when Guitarix's JSON-RPC server returns an error response."""


class GuitarixRPC:
    def __init__(self, host="127.0.0.1", port=7777, timeout=0.3):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._lock = threading.Lock()
        self._sock = None
        self._next_id = 1
        self._last_failure_time = None

    def _connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)

    def _call(self, method, params=None):
        """Send one JSON-RPC request and return its `result`. Reconnects once on a
        stale/broken socket before giving up."""
        request = json.dumps({
            "jsonrpc": "2.0", "method": method, "params": params or [], "id": self._next_id,
        }) + "\n"
        with self._lock:
            self._next_id += 1
            if (
                self._sock is None
                and self._last_failure_time is not None
                and time.monotonic() - self._last_failure_time < RECONNECT_BACKOFF
            ):
                raise OSError("Guitarix RPC recently unreachable, not retrying yet")
            for attempt in range(2):
                try:
                    if self._sock is None:
                        self._connect()
                    self._sock.sendall(request.encode())
                    buf = b""
                    while True:
                        chunk = self._sock.recv(65536)
                        if not chunk:
                            raise OSError("Guitarix closed the RPC connection")
                        buf += chunk
                        try:
                            response = json.loads(buf.decode())
                            break
                        except json.JSONDecodeError:
                            continue  # response spans more than one recv()
                    break
                except OSError:
                    self._sock = None
                    if attempt == 1:
                        self._last_failure_time = time.monotonic()
                        raise
        error = response.get("error")
        if error:
            raise GuitarixRPCError(error.get("message", "unknown Guitarix RPC error"))
        return response["result"]

    def get_current_bank(self):
        result = self._call("get_parameter", ["system.current_bank"])
        return result["system.current_bank"]["value"]["system.current_bank"]

    def get_current_preset(self):
        result = self._call("get_parameter", ["system.current_preset"])
        return result["system.current_preset"]["value"]["system.current_preset"]

    def get_bank_presets(self, bank_name):
        """Ordered preset names for `bank_name` (order matches MIDI Program Change numbers)."""
        result = self._call("get_bank", [bank_name])
        return result["presets"]
