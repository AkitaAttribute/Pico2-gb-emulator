import sys
sys.path.insert(0,'.')
from gb.core import GameBoy
rom=bytearray(0x8000)
rom[0x100:0x106]=bytes((0x3E,0x42,0xEA,0x00,0xC0,0x76))
gb=GameBoy(rom,lambda y,line:None)
for _ in range(8):gb.cpu.step()
assert gb.bus.wram[0]==0x42
assert gb.cpu.halted
print('smoke ok')
