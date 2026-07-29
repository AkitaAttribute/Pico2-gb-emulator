import gc,os,time,_thread
from machine import freq
from gb.core import GameBoy
from gb.display import ILI9341,worker
from gb.input import Buttons
from gb.ring import ScanlineRing

try:freq(351_000_000)
except Exception:pass

def choose_rom():
    files=[]
    for root in ('/sd','/'):
        try:
            for n in os.listdir(root):
                if n.lower().endswith('.gb'):files.append(root.rstrip('/')+'/'+n)
        except OSError:pass
    if not files:raise OSError('Copy a .gb ROM to / or /sd')
    files.sort();print('ROM:',files[0]);return files[0]

def install_disconnected_serial(bus):
    """Make the Game Boy serial port behave as if no link cable is attached.

    Reads return an idle/open-bus value. Starting a transfer completes it
    immediately with 0xFF received and raises the serial interrupt, preventing
    games from hanging while waiting for link hardware that does not exist.
    """
    original_read=bus.read8
    original_write=bus.write8

    def read8(address):
        address&=0xFFFF
        if address==0xFF01:return bus.io[1]
        if address==0xFF02:return bus.io[2]|0x7C
        return original_read(address)

    def write8(address,value):
        address&=0xFFFF;value&=0xFF
        if address==0xFF01:
            bus.io[1]=value
            return
        if address==0xFF02:
            bus.io[2]=value&0x7F
            if value&0x80:
                bus.io[1]=0xFF
                bus.iflag|=0x08
            return
        original_write(address,value)

    bus.read8=read8
    bus.write8=write8

def tick_runtime_rtc(cart,seconds):
    """Advance MBC3 time only while this emulator session is running."""
    if cart.kind not in (0x0F,0x10,0x11,0x12,0x13) or seconds<=0:return
    rtc=cart.rtc
    if rtc[4]&0x40:return
    total=rtc[0]+rtc[1]*60+rtc[2]*3600+seconds
    rtc[0]=total%60
    total//=60;rtc[1]=total%60
    total//=60;rtc[2]=total%24
    days=((rtc[4]&1)<<8)|rtc[3]
    days+=total//24
    if days>511:
        days%=512
        rtc[4]|=0x80
    rtc[3]=days&0xFF
    rtc[4]=(rtc[4]&0xC0)|((days>>8)&1)

rom_path=choose_rom()
with open(rom_path,'rb') as f:rom=f.read()
save_path=rom_path.rsplit('.',1)[0]+'.sav'
ring=ScanlineRing();buttons=Buttons();display=ILI9341()
_thread.start_new_thread(worker,(ring,display))

def line_sink(y,data):
    i,out=ring.acquire_write();out[:]=data;ring.publish(i,y)

gb=GameBoy(rom,line_sink,buttons.read,save_path)
install_disconnected_serial(gb.bus)
gc.collect();gc.disable();frames=0;t0=time.ticks_ms();last_save=t0;rtc_tick=t0
try:
    while True:
        gb.run_frame();frames+=1;now=time.ticks_ms()
        elapsed_rtc=time.ticks_diff(now,rtc_tick)
        if elapsed_rtc>=1000:
            seconds=elapsed_rtc//1000
            tick_runtime_rtc(gb.cart,seconds)
            rtc_tick=time.ticks_add(rtc_tick,seconds*1000)
        if time.ticks_diff(now,t0)>=5000:
            print('fps',frames*1000//time.ticks_diff(now,t0));frames=0;t0=now
        if time.ticks_diff(now,last_save)>=30000:
            gb.save();last_save=now
finally:gb.save()
