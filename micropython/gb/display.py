import micropython,time
from machine import Pin,SPI
NATIVE_WIDTH=160;NATIVE_HEIGHT=144;OUTPUT_WIDTH=320;OUTPUT_HEIGHT=240
@micropython.viper
def scale_2x(source,dest):
    src=ptr8(source);dst=ptr8(dest);i=0
    while i<NATIVE_WIDTH:
        a=src[i*2];b=src[i*2+1];o=i*4;dst[o]=a;dst[o+1]=b;dst[o+2]=a;dst[o+3]=b;i+=1
class ILI9341:
    def __init__(self,spi_id=0,sck=2,mosi=3,cs=4,dc=7,reset=8,baudrate=62_500_000):
        self.spi=SPI(spi_id,baudrate=baudrate,polarity=0,phase=0,bits=8,firstbit=SPI.MSB,sck=Pin(sck),mosi=Pin(mosi))
        self.cs=Pin(cs,Pin.OUT,value=1);self.dc=Pin(dc,Pin.OUT,value=1);self.reset=Pin(reset,Pin.OUT,value=1);self.scaled=bytearray(640);self._init()
    def _write(self,c,d=None):
        self.cs(0);self.dc(0);self.spi.write(bytes((c,)))
        if d:self.dc(1);self.spi.write(d)
        self.cs(1)
    def _init(self):
        self.reset(0);time.sleep_ms(20);self.reset(1);time.sleep_ms(120);self._write(1);time.sleep_ms(120);self._write(0x3A,b'\x55');self._write(0x36,b'\x28');self._write(0x11);time.sleep_ms(120);self._write(0x29)
    def line(self,src,y):
        scale_2x(src,self.scaled);a=(y*OUTPUT_HEIGHT+NATIVE_HEIGHT-1)//NATIVE_HEIGHT;b=((y+1)*OUTPUT_HEIGHT+NATIVE_HEIGHT-1)//NATIVE_HEIGHT
        self._write(0x2A,bytes((0,0,1,0x3F)));self._write(0x2B,bytes((a>>8,a&255,(b-1)>>8,(b-1)&255)));self._write(0x2C);self.cs(0);self.dc(1)
        for _ in range(b-a):self.spi.write(self.scaled)
        self.cs(1)
def worker(ring,display):
    while True:
        i,y,line=ring.acquire_read();display.line(line,y);ring.release(i)
