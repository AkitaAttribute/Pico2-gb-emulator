use core::cell::UnsafeCell;
use core::sync::atomic::{AtomicU8, Ordering};

use embedded_graphics::pixelcolor::raw::RawU16;
use embedded_graphics::pixelcolor::Rgb565;
use gb_core::hardware::Screen;

pub const NATIVE_WIDTH: usize = 160;
pub const NATIVE_HEIGHT: usize = 144;
const FRAME_PIXELS: usize = NATIVE_WIDTH * NATIVE_HEIGHT;
const BUFFER_COUNT: usize = 2;

const FREE: u8 = 0;
const WRITING: u8 = 1;
const READY: u8 = 2;
const READING: u8 = 3;

#[const_env::from_env]
const FRAME_RATE: u8 = 30;

/// Two native-resolution frame buffers shared by the two RP2350 cores.
///
/// Core 0 is the only writer and Core 1 is the only reader. Atomic state
/// transitions transfer ownership of each buffer between the cores.
pub struct FrameQueue {
    buffers: UnsafeCell<[[u16; FRAME_PIXELS]; BUFFER_COUNT]>,
    states: [AtomicU8; BUFFER_COUNT],
}

// Access to `buffers` is protected by the ownership encoded in `states`.
unsafe impl Sync for FrameQueue {}

impl FrameQueue {
    pub const fn new() -> Self {
        Self {
            buffers: UnsafeCell::new([[0; FRAME_PIXELS]; BUFFER_COUNT]),
            states: [AtomicU8::new(FREE), AtomicU8::new(FREE)],
        }
    }

    fn claim_free_buffer(&self) -> usize {
        loop {
            for index in 0..BUFFER_COUNT {
                if self.states[index]
                    .compare_exchange(FREE, WRITING, Ordering::AcqRel, Ordering::Acquire)
                    .is_ok()
                {
                    return index;
                }
            }
            core::hint::spin_loop();
        }
    }

    fn publish(&self, index: usize) {
        self.states[index].store(READY, Ordering::Release);
    }

    fn claim_ready_buffer(&self) -> usize {
        loop {
            for index in 0..BUFFER_COUNT {
                if self.states[index]
                    .compare_exchange(READY, READING, Ordering::AcqRel, Ordering::Acquire)
                    .is_ok()
                {
                    return index;
                }
            }
            core::hint::spin_loop();
        }
    }

    fn release(&self, index: usize) {
        self.states[index].store(FREE, Ordering::Release);
    }

    #[inline(always)]
    unsafe fn write_pixel(&self, buffer: usize, pixel: usize, value: u16) {
        (*self.buffers.get())[buffer][pixel] = value;
    }

    #[inline(always)]
    unsafe fn read_pixel(&self, buffer: usize, pixel: usize) -> u16 {
        (*self.buffers.get())[buffer][pixel]
    }
}

pub static FRAME_QUEUE: FrameQueue = FrameQueue::new();

/// Screen implementation used by the Game Boy emulation running on Core 0.
/// It writes complete native frames and publishes them to Core 1.
pub struct MulticoreFrameBufferDisplay {
    write_buffer: usize,
}

impl MulticoreFrameBufferDisplay {
    pub fn new() -> Self {
        Self {
            write_buffer: FRAME_QUEUE.claim_free_buffer(),
        }
    }
}

impl Screen for MulticoreFrameBufferDisplay {
    fn turn_on(&mut self) {}

    fn turn_off(&mut self) {}

    #[inline(always)]
    fn set_pixel(&mut self, x: u8, y: u8, color: gb_core::hardware::color_palette::Color) {
        let encoded_color = ((color.red as u16 & 0b1111_1000) << 8)
            | ((color.green as u16 & 0b1111_1100) << 3)
            | (color.blue as u16 >> 3);
        let pixel = y as usize * NATIVE_WIDTH + x as usize;
        unsafe {
            FRAME_QUEUE.write_pixel(self.write_buffer, pixel, encoded_color);
        }
    }

    fn scanline_complete(&mut self, _y: u8, _skip: bool) {}

    fn draw(&mut self, _skip: bool) {
        FRAME_QUEUE.publish(self.write_buffer);
        self.write_buffer = FRAME_QUEUE.claim_free_buffer();
    }

    fn frame_rate(&self) -> u8 {
        FRAME_RATE
    }
}

/// Native-frame iterator used by Core 1. Construct one iterator for each
/// display refresh; it blocks until Core 0 publishes the next frame.
pub struct FrameQueueIterator {
    read_buffer: Option<usize>,
    pixel: usize,
}

impl FrameQueueIterator {
    pub const fn new() -> Self {
        Self {
            read_buffer: None,
            pixel: 0,
        }
    }

    fn finish(&mut self) {
        if let Some(index) = self.read_buffer.take() {
            FRAME_QUEUE.release(index);
        }
    }
}

impl Iterator for FrameQueueIterator {
    type Item = Rgb565;

    #[inline(always)]
    fn next(&mut self) -> Option<Self::Item> {
        if self.read_buffer.is_none() {
            self.read_buffer = Some(FRAME_QUEUE.claim_ready_buffer());
        }

        if self.pixel >= FRAME_PIXELS {
            self.finish();
            return None;
        }

        let index = self.read_buffer.unwrap();
        let raw = unsafe { FRAME_QUEUE.read_pixel(index, self.pixel) };
        self.pixel += 1;
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
        self.finish();
    }
}
