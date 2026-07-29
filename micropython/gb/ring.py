import _thread

NATIVE_WIDTH = 160
RING_LINES = 4


class ScanlineRing:
    """Single-producer/single-consumer scanline ring.

    Core 0 publishes 160-pixel RGB565 scanlines. Core 1 consumes them in order.
    Locks are deliberately short; no allocation occurs in the hot path.
    """

    def __init__(self):
        self._lines = [bytearray(NATIVE_WIDTH * 2) for _ in range(RING_LINES)]
        self._line_numbers = bytearray(RING_LINES)
        self._ready = bytearray(RING_LINES)
        self._write_index = 0
        self._read_index = 0
        self._lock = _thread.allocate_lock()

    def acquire_write(self):
        while True:
            with self._lock:
                index = self._write_index
                if self._ready[index] == 0:
                    return index, self._lines[index]
            _thread.yield_thread()

    def publish(self, index, line_number):
        with self._lock:
            self._line_numbers[index] = line_number
            self._ready[index] = 1
            self._write_index = (index + 1) % RING_LINES

    def acquire_read(self):
        while True:
            with self._lock:
                index = self._read_index
                if self._ready[index]:
                    return index, self._line_numbers[index], self._lines[index]
            _thread.yield_thread()

    def release(self, index):
        with self._lock:
            self._ready[index] = 0
            self._read_index = (index + 1) % RING_LINES
