# MicroPython RP2350 Game Boy emulator

This branch contains an executable DMG emulator rewrite in MicroPython. It includes the documented LR35902 opcode set and CB instructions, interrupts, timers, DMA, joypad input, scanline PPU rendering with background/window/sprites, MBC1/MBC2/MBC3/MBC5 banking, battery RAM saves, ROM discovery, and the dual-core LCD pipeline.

## Install

1. Flash a recent RP2350 MicroPython firmware with `_thread` support.
2. Copy `main.py` and the `gb` directory to the board.
3. Copy a `.gb` ROM to `/`, or mount an SD card at `/sd` and copy it there.
4. Adjust display pins in `gb/display.py` and input pins in `gb/input.py` if necessary.
5. Reset the board. The alphabetically first ROM is loaded.

The emulator writes `<romname>.sav` every 30 seconds and on a clean exit.

## Accuracy limits

This is a testable first full rewrite, not a cycle-perfect emulator. The PPU renders at completed-scanline granularity, MBC3 RTC does not advance in real time, illegal CPU opcodes act as NOP, and audio output is not implemented. Games depending on precise STAT timing, serial hardware, RTC behavior, or audio synchronization may fail.

## Validation

GitHub Actions compiles the portable emulator core with Python 3.12 and runs a synthetic-ROM smoke test that verifies instruction execution, memory writes, and HALT behavior. MicroPython Viper and physical LCD/input behavior still require the RP2350.
