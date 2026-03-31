"""
Simulated Random Number Generator.

Mimics the Raspberry Pi Pico's actual output ranges:
  PRNG   — LCG, 32-bit (0 to 4294967295)
  TRNG   — ADC read_u16, 16-bit (0 to 65535)
  HYBRID — XOR of PRNG and TRNG

Provides the same async-generator interface as SerialReader
so the dashboard can be developed/tested without hardware.
"""

import asyncio
import os
import time
import logging

logger = logging.getLogger(__name__)


class LCG:
    """Linear Congruential Generator matching the Pico's parameters."""

    def __init__(self, seed: int | None = None):
        self.state = seed if seed is not None else int(time.time() * 1e6) & 0xFFFFFFFF
        self.a = 1664525
        self.c = 1013904223
        self.m = 0x100000000  # 2^32

    def next(self) -> int:
        self.state = (self.a * self.state + self.c) % self.m
        return self.state  # full 32-bit value


class Simulator:
    """Drop-in replacement for SerialReader that generates synthetic data."""

    def __init__(self, interval: float = 0.05):
        self.interval = interval  # seconds between values (slower like real Pico)
        self.mode = "PRNG"        # Pico starts in PRNG mode (mode 0)
        self._lcg = LCG()

    def set_mode(self, mode: str):
        mode = mode.upper()
        if mode in ("TRNG", "PRNG", "HYBRID"):
            self.mode = mode
            logger.info("Simulator mode set to %s", self.mode)

    def _generate(self) -> int:
        if self.mode == "PRNG":
            return self._lcg.next()                              # 32-bit
        elif self.mode == "TRNG":
            return int.from_bytes(os.urandom(2), "big")          # 16-bit (0-65535)
        else:  # HYBRID
            prng_val = self._lcg.next()
            trng_val = int.from_bytes(os.urandom(2), "big")
            return prng_val ^ trng_val

    async def read_values(self):
        """Async generator yielding (mode, value) tuples at a fixed rate."""
        while True:
            value = self._generate()
            yield self.mode, value
            await asyncio.sleep(self.interval)
