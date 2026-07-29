# Experimental MicroPython rewrite

This directory is a clean MicroPython implementation target for the RP2350 version of the project. It begins with the performance-critical hardware pipeline rather than pretending the existing Rust emulator core can be mechanically translated.

## Current state

Implemented:

- RP2350 dual-core startup through `_thread`.
- Core 0 scanline production and Core 1 LCD consumption.
- Four-line, allocation-free producer/consumer ring.
- RGB565 160-to-320 horizontal scaling using the Viper emitter.
- 144-to-240 vertical line repetition.
- Direct ILI9341 SPI output.
- Bootable animated throughput benchmark with FPS reporting.

Not yet ported:

- LR35902 CPU and CB-prefixed instruction set.
- Interrupt, timer and DMA timing.
- PPU modes, sprites, windows and palettes.
- APU channels and I2S output.
- MBC1/MBC2/MBC3/MBC5 cartridge controllers.
- RTC and battery-backed saves.
- SD-card ROM browser and ROM cache.
- Boot ROM behavior and compatibility testing.

## Why MicroPython rather than CircuitPython

The design depends on a second RP2350 core. MicroPython exposes `_thread` on RP2 targets and offers native and Viper emitters for hot integer loops. CircuitPython provides PIO support, but it is not a suitable target for this particular dual-core execution model.

## Running the benchmark

1. Flash a recent RP2350 MicroPython build.
2. Copy the contents of this directory to the board filesystem.
3. Confirm the LCD pin definitions in `main.py`.
4. Reset the board.

The benchmark reports pipeline FPS over USB serial. It measures Python scanline generation, cross-core transfer, scaling and LCD transmission; it does not yet measure Game Boy emulation.

## Performance expectation

A pure Python LR35902 interpreter is unlikely to approach the Rust implementation. The practical route is expected to be:

- MicroPython for startup, menu, storage and orchestration.
- Viper or inline Thumb assembly for fixed pixel and memory operations.
- A native MicroPython user module for the CPU/PPU/APU core if profiling confirms Python dispatch is the limiting factor.

That still produces a MicroPython application, while avoiding an interpreter-within-an-interpreter design for every emulated CPU instruction.
