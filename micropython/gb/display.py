import micropython
import time
from machine import Pin, SPI

NATIVE_WIDTH = 160
NATIVE_HEIGHT = 144
OUTPUT_WIDTH = 320
OUTPUT_HEIGHT = 240


@micropython.viper
def scale_2x_rgb565(source, destination):
    src = ptr8(source)
    dst = ptr8(destination)
    source_pixel = 0
    destination_pixel = 0
    while source_pixel < NATIVE_WIDTH:
        high = src[source_pixel * 2]
        low = src[source_pixel * 2 + 1]
        offset = destination_pixel * 2
        dst[offset] = high
        dst[offset + 1] = low
        dst[offset + 2] = high
        dst[offset + 3] = low
        source_pixel += 1
        destination_pixel += 2


class ILI9341:
    def __init__(self, spi_id, sck, mosi, cs, dc, reset, baudrate=62_500_000):
        self.spi = SPI(
            spi_id,
            baudrate=baudrate,
            polarity=0,
            phase=0,
            bits=8,
            firstbit=SPI.MSB,
            sck=Pin(sck),
            mosi=Pin(mosi),
        )
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.dc = Pin(dc, Pin.OUT, value=1)
        self.reset = Pin(reset, Pin.OUT, value=1)
        self._scaled_line = bytearray(OUTPUT_WIDTH * 2)
        self._reset_and_init()

    def _write(self, command, data=None):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes((command,)))
        if data:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def _reset_and_init(self):
        self.reset(0)
        time.sleep_ms(20)
        self.reset(1)
        time.sleep_ms(120)
        self._write(0x01)
        time.sleep_ms(120)
        self._write(0x3A, b"\x55")  # RGB565
        self._write(0x36, b"\x28")  # landscape/BGR; board-specific
        self._write(0x11)
        time.sleep_ms(120)
        self._write(0x29)

    def _set_window(self, x0, y0, x1, y1):
        self._write(0x2A, bytes((x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)))
        self._write(0x2B, bytes((y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)))
        self._write(0x2C)

    def write_native_line(self, source_line, source_y):
        scale_2x_rgb565(source_line, self._scaled_line)
        start = (source_y * OUTPUT_HEIGHT + NATIVE_HEIGHT - 1) // NATIVE_HEIGHT
        end = ((source_y + 1) * OUTPUT_HEIGHT + NATIVE_HEIGHT - 1) // NATIVE_HEIGHT
        repeats = end - start
        if repeats <= 0:
            return
        self._set_window(0, start, OUTPUT_WIDTH - 1, end - 1)
        self.cs(0)
        self.dc(1)
        for _ in range(repeats):
            self.spi.write(self._scaled_line)
        self.cs(1)


def display_worker(ring, display):
    while True:
        index, line_number, line = ring.acquire_read()
        display.write_native_line(line, line_number)
        ring.release(index)
