import _thread
import gc
import time
from machine import Pin, freq

from gb.display import ILI9341, display_worker
from gb.ring import NATIVE_WIDTH, ScanlineRing

# Match the Rust project's current overclock. Stability varies by board.
freq(351_000_000)

PIN_SCREEN_CS = 4
PIN_SCREEN_SCLK = 2
PIN_SCREEN_MOSI = 3
PIN_SCREEN_DC = 7
PIN_SCREEN_RESET = 8

ring = ScanlineRing()
display = ILI9341(
    spi_id=0,
    sck=PIN_SCREEN_SCLK,
    mosi=PIN_SCREEN_MOSI,
    cs=PIN_SCREEN_CS,
    dc=PIN_SCREEN_DC,
    reset=PIN_SCREEN_RESET,
)

_thread.start_new_thread(display_worker, (ring, display))


def fill_test_line(line, y, frame):
    """Allocation-free RGB565 diagnostic producer for pipeline benchmarking."""
    x = 0
    while x < NATIVE_WIDTH:
        red = (x + frame) & 0x1F
        green = (y + frame) & 0x3F
        blue = ((x >> 1) + y) & 0x1F
        color = (red << 11) | (green << 5) | blue
        offset = x * 2
        line[offset] = color >> 8
        line[offset + 1] = color & 0xFF
        x += 1


gc.collect()
gc.disable()
frame = 0
start = time.ticks_ms()

while True:
    y = 0
    while y < 144:
        index, line = ring.acquire_write()
        fill_test_line(line, y, frame)
        ring.publish(index, y)
        y += 1

    frame += 1
    if frame % 30 == 0:
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, start)
        if elapsed:
            print("pipeline fps:", (30_000 // elapsed))
        start = now
