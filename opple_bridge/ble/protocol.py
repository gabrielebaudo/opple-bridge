"""NUS protocol implementation for Opple Light Master.

Based on the reverse-engineered protocol from open-light-master (OlliV/open-light-master).
Uses the Nordic UART Service (NUS) over BLE GATT.

Protocol confirmed working on both G3 and G4 (SigMesh) via g4_probe.py.

Key findings:
  - Both RX and TX characteristics support write-without-response on the G4
  - open-light-master writes to TX (6e400003) and receives notifications on TX
  - Commands must be wrapped in fragmentation frames before sending
  - Inner header is 11 bytes: [00 13 00 00 seqno 00 payload_len 00 00 opcode_hi opcode_lo]
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Nordic UART Service UUIDs
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# Write commands to TX characteristic (confirmed by open-light-master and g4_probe)
NUS_WRITE_UUID = NUS_TX_UUID
NUS_NOTIFY_UUID = NUS_TX_UUID

# Opcodes
REQ_MEAS = 0x0A00
RES_MEAS = 0x0A01
REQ_FREQ = 0x0A0A
RES_FREQ = 0x0A0B
REQ_CALIB = 0x0A04
RES_CALIB = 0x0A05

# Fragment types (upper 3 bits of first byte)
FRAG_SINGLE = 0x00
FRAG_FIRST = 0x80
FRAG_MIDDLE = 0xA0
FRAG_LAST = 0xC0
FRAG_TYPE_MASK = 0xE0


def build_command(opcode: int, payload: bytes = b"", seq_no: int = 0) -> bytes:
    """Build the 11-byte inner NUS command header + payload.

    This is the inner protocol layer. Must be wrapped with encapsulate()
    before sending over BLE.

    Header layout:
        [0]    = 0x00
        [1]    = 0x13 (protocol marker)
        [2-3]  = 0x00, 0x00
        [4]    = sequence number
        [5]    = 0x00
        [6]    = payload length
        [7-8]  = 0x00, 0x00
        [9-10] = opcode (big-endian)
    """
    return bytes([
        0x00, 0x13, 0x00, 0x00,
        seq_no & 0xFF,
        0x00,
        len(payload) & 0xFF,
        0x00, 0x00,
        (opcode >> 8) & 0xFF,
        opcode & 0xFF,
    ]) + payload


def encapsulate(data: bytes) -> list[bytes]:
    """Wrap inner command data in BLE fragmentation frames.

    Replicates open-light-master's encapsulateData() exactly.

    Frame format:
      SINGLE: [0x00, len_hi, len_lo, ...all data...]
      FIRST:  [0x80, total_len_hi, total_len_lo, ...first 17 bytes...]
      MIDDLE: [0xA0|idx, ...up to 19 bytes...]
      LAST:   [0xC0|idx, ...remaining bytes...]
    """
    n_frags = 1 if len(data) < 17 else ((len(data) - 17 + 18) // 19 + 1)
    frames = []

    for c in range(n_frags):
        if c == 0:
            total_len = len(data) + n_frags + 2
            header = bytes([
                FRAG_FIRST if n_frags > 1 else FRAG_SINGLE,
                (total_len >> 8) & 0xFF,
                total_len & 0xFF,
            ])
            body = data[:17] if n_frags > 1 else data
        elif c < n_frags - 1:
            header = bytes([FRAG_MIDDLE | c])
            body = data[17 + 19 * (c - 1):17 + 19 * c]
        else:
            header = bytes([FRAG_LAST | c])
            body = data[17 + 19 * (c - 1):]

        frames.append(header + body)

    return frames


class MessageAssembler:
    """Reassembles fragmented NUS messages.

    The Opple device fragments large responses into multiple BLE notifications.
    Fragment type is determined by the upper 3 bits (& 0xE0) of the first byte.

    Frame format:
      SINGLE (0x00): [type(1) + len(2)] + inner_data
      FIRST  (0x80): [type(1) + total_len(2)] + first_payload (up to 17 bytes)
      MIDDLE (0xA0): [type|idx(1)] + payload (up to 19 bytes)
      LAST   (0xC0): [type|idx(1)] + remaining_payload

    The assembled result is the inner protocol data (11-byte header + payload)
    with all fragmentation headers stripped.
    """

    def __init__(self, on_message: Callable[[bytes], None]):
        self._buffer = bytearray()
        self._on_message = on_message

    def feed(self, data: bytes) -> None:
        """Process an incoming BLE notification."""
        if not data:
            return

        frag_type = data[0] & FRAG_TYPE_MASK

        if frag_type == FRAG_SINGLE:
            # Strip 3-byte fragmentation header, deliver inner data
            self._buffer.clear()
            self._on_message(bytes(data[3:]))

        elif frag_type == FRAG_FIRST:
            # Strip 3-byte header, store inner data
            self._buffer = bytearray(data[3:])

        elif frag_type == FRAG_MIDDLE:
            # Strip 1-byte header, append
            if self._buffer:
                self._buffer.extend(data[1:])
            else:
                logger.warning("Received MIDDLE fragment without FIRST, discarding")

        elif frag_type == FRAG_LAST:
            # Strip 1-byte header, append, deliver
            if self._buffer:
                self._buffer.extend(data[1:])
                self._on_message(bytes(self._buffer))
                self._buffer.clear()
            else:
                logger.warning("Received LAST fragment without FIRST, discarding")

        else:
            logger.warning("Unknown fragment type: 0x%02X", data[0])

    def reset(self) -> None:
        """Clear the reassembly buffer."""
        self._buffer.clear()
