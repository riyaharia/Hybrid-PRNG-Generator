"""
Serial Data Acquisition module.

Reads random numbers from a Raspberry Pi Pico over USB serial.
Expected line format: MODE:VALUE\n  (e.g. "TRNG:142\n")
"""

import asyncio
import serial
import logging

logger = logging.getLogger(__name__)


class SerialReader:
    """Async wrapper around a PySerial connection to the Pico."""

    def __init__(self, port: str = "COM5", baud_rate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self._serial: serial.Serial | None = None

    def open(self):
        """Open the serial connection."""
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baud_rate,
            timeout=self.timeout,
        )
        logger.info("Serial port %s opened at %d baud", self.port, self.baud_rate)

    def close(self):
        """Close the serial connection."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            logger.info("Serial port %s closed", self.port)

    async def read_values(self):
        """
        Async generator that yields (mode, value) tuples from the serial port.
        Runs serial reads in a thread executor to avoid blocking the event loop.
        """
        if not self._serial or not self._serial.is_open:
            self.open()

        loop = asyncio.get_event_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, self._serial.readline)
                if not line:
                    continue
                decoded = line.decode("utf-8", errors="ignore").strip()
                if ":" not in decoded:
                    continue
                mode, val_str = decoded.split(":", 1)
                mode = mode.strip().upper()
                value = int(val_str.strip())
                yield mode, value
            except (ValueError, UnicodeDecodeError) as exc:
                logger.warning("Bad serial line: %s", exc)
                continue
            except serial.SerialException as exc:
                logger.error("Serial error: %s", exc)
                break
