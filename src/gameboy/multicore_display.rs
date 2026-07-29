use core::cell::UnsafeCell;
use core::sync::atomic::{AtomicU8, Ordering};

use embedded_graphics::pixelcolor::raw::RawU16;
use embedded_graphics::pixelcolor::Rgb565;
use gb_core::hardware::Screen;

pub const NATIVE_WIDTH: usize = 160;
pub const NATIVE_HEIGHT: usize = 144;
const FRAME_PIXELS: usize = NATIVE_WIDTH * NATIVE_HEIGHT;
const BUFFER_COUNT: usize = 4;

const FREE: u8 = 0;
const WRITING: u8 = 1;
const READY: u8 = 2;
const READING: u8 = 3;

#[const_env::from_env]
const FRAME_RATE: u8 = 30;

/// Small single-producer/single-consumer scanline ring shared by both cores.
///
/// Core 0 writes Game Boy scanlines in order. Core 1 consumes those scanlines
/// in the same order while scaling and submitting pixels to the LCD DMA path.
pub struct ScanlineQueue {
    buffers: UnsafeCell<[[u16; NATIVE_WIDTH]; BUFFER_COUNT]>,
    states: [AtomicU8; BUFFER_COUNT],
}

// A slot is accessed by only the core that owns its state.
unsafe impl Sync for ScanlineQueue {}

impl ScanlineQueue {
    pub const fn new() -> Self {
        Self {
            buffers: UnsafeCell::new([[0; NATIVE_WIDTH]; BUFFER_COUNT]),
            states: [
                AtomicU8::new(FREE),
                AtomicU8::new(FREE),
                AtomicU8::new(FREE),
                AtomicU8::new(FREE),
            ],
        }
    }

    fn claim_for_write(&self, slot: usize) {
        while self.states[slot]
            .compare_exchange(FREE, WRITING, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            core::hint::spin_loop();
        }
    }

    fn publish(&self, slot: usize) {
        self.states[slot].store(READY, Ordering::Release);
    }

    fn claim_for_read(&self, slot: usize) {
        while self.states[slot]
            .compare_exchange(READY, READING, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            core::hint::spin_loop();
        }
    }

    fn release(&self, slot: usize) {
        self.states[slot].store(FREE, Ordering::Release);
    }

    #[inline(always)]
    unsafe fn write_pixel(&self, slot: usize, x: usize, value: u16) {
        (*self.buffers.get())[slot][x] = value;
    }

    #[inline(always)]
    unsafe fn read_pixel(&self, slot: usize, x: usize) -> u16 {
        (*self.buffers.get())[slot][x]
    }
}

pub static SCANLINE_QUEUE: ScanlineQueue = ScanlineQueue::new();

/// Screen implementation used by the authoritative emulator on Core 0.
pub struct MulticoreFrameBufferDisplay {
    write_slot: usize,
}

impl MulticoreFrameBufferDisplay {
    pub fn new() -> Self {
        SCANLINE_QUEUE.claim_for_write(0);
        Self { write_slot: 0 }
    }
}

impl Screen for MulticoreFrameBufferDisplay {
    fn turn_on(&mut self) {}

    fn turn_off(&mut self) {}

    #[inline(always)]
    fn set_pixel(&mut self, x: u8, _y: u8, color: gb_core::hardware::color_palette::Color) {
        let encoded_color = ((color.red as u16 & 0b1111_1000) << 8)
            | ((color.green as u16 & 0b1111_1100) << 3)
            | (color.blue as u16 >> 3);
        unsafe {
            SCANLINE_QUEUE.write_pixel(self.write_slot, x as usize, encoded_color);
        }
    }

    #[inline(always)]
    fn scanline_complete(&mut self, _y: u8, _skip: bool) {
        SCANLINE_QUEUE.publish(self.write_slot);
        self.write_slot = (self.write_slot + 1) % BUFFER_COUNT;
        SCANLINE_QUEUE.claim_for_write(self.write_slot);
    }

    fn draw(&mut self, _skip: bool) {}

    fn frame_rate(&self) -> u8 {
        FRAME_RATE
    }
}

/// Iterator used by Core 1 for one complete native frame.
///
/// Each line is released immediately after its last pixel has been read, so
/// Core 0 can reuse that slot while Core 1 is scaling or transmitting later
/// lines in the same frame.
pub struct FrameQueueIterator {
    read_slot: usize,
    x: usize,
    pixel: usize,
    slot_claimed: bool,
}

impl FrameQueueIterator {
    pub const fn new() -> Self {
        Self {
            read_slot: 0,
            x: 0,
            pixel: 0,
            slot_claimed: false,
        }
    }

    fn release_current_slot(&mut self) {
        if self.slot_claimed {
            SCANLINE_QUEUE.release(self.read_slot);
            self.read_slot = (self.read_slot + 1) % BUFFER_COUNT;
            self.slot_claimed = false;
        }
    }
}

impl Iterator for FrameQueueIterator {
    type Item = Rgb565;

    #[inline(always)]
    fn next(&mut self) -> Option<Self::Item> {
        if self.pixel >= FRAME_PIXELS {
            self.release_current_slot();
            return None;
        }

        if !self.slot_claimed {
            SCANLINE_QUEUE.claim_for_read(self.read_slot);
            self.slot_claimed = true;
        }

        let raw = unsafe { SCANLINE_QUEUE.read_pixel(self.read_slot, self.x) };
        self.x += 1;
        self.pixel += 1;

        if self.x == NATIVE_WIDTH {
            self.x = 0;
            self.release_current_slot();
        }

        Some(Rgb565::from(RawU16::new(raw)))
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let remaining = FRAME_PIXELS.saturating_sub(self.pixel);
        (remaining, Some(remaining))
    }
}

impl ExactSizeIterator for FrameQueueIterator {}

impl Drop for FrameQueueIterator {
    fn drop(&mut self) {
        self.release_current_slot();
    }
}
