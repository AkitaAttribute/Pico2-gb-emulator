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

rom_path=choose_rom()
with open(rom_path,'rb') as f:rom=f.read()
save_path=rom_path.rsplit('.',1)[0]+'.sav'
ring=ScanlineRing();buttons=Buttons();display=ILI9341()
_thread.start_new_thread(worker,(ring,display))

def line_sink(y,data):
    i,out=ring.acquire_write();out[:]=data;ring.publish(i,y)

gb=GameBoy(rom,line_sink,buttons.read,save_path)
gc.collect();gc.disable();frames=0;t0=time.ticks_ms();last_save=t0
try:
    while True:
        gb.run_frame();frames+=1;now=time.ticks_ms()
        if time.ticks_diff(now,t0)>=5000:
            print('fps',frames*1000//time.ticks_diff(now,t0));frames=0;t0=now
        if time.ticks_diff(now,last_save)>=30000:
            gb.save();last_save=now
finally:gb.save()
