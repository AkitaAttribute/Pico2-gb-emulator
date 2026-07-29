"""Small DMG Game Boy emulator core for MicroPython.

The implementation favors compactness and portability over cycle-perfect behavior. It
implements the complete documented LR35902 opcode space, timers, interrupts, common
MBCs, joypad input, DMA, and a scanline renderer suitable for the dual-core display
pipeline.
"""

try:
    import micropython
except ImportError:
    class _MP:
        def native(self, fn): return fn
        def viper(self, fn): return fn
    micropython = _MP()

FLAG_Z = 0x80
FLAG_N = 0x40
FLAG_H = 0x20
FLAG_C = 0x10
DMG_PALETTE = (0xFFFF, 0xBDF7, 0x7BEF, 0x0000)

def _s8(v): return v - 256 if v & 0x80 else v

class Cartridge:
    def __init__(self, rom, save_path=None):
        self.rom=rom; self.save_path=save_path
        self.kind=rom[0x147] if len(rom)>0x147 else 0
        self.ram_size={0:0,1:2048,2:8192,3:32768,4:131072,5:65536}.get(rom[0x149] if len(rom)>0x149 else 0,0)
        self.ram=bytearray(self.ram_size); self.ram_enabled=False; self.rom_bank=1; self.ram_bank=0
        self.mode=0; self.mbc1_hi=0; self.rtc_select=0; self.rtc=bytearray(5)
        if save_path:
            try:
                with open(save_path,'rb') as f:
                    d=f.read(); self.ram[:min(len(d),len(self.ram))]=d[:len(self.ram)]
            except OSError: pass
    def save(self):
        if self.save_path and self.ram:
            try:
                with open(self.save_path,'wb') as f: f.write(self.ram)
            except OSError: pass
    def read(self,a):
        if a<0x4000:
            bank=(self.mbc1_hi<<5) if self.kind in (1,2,3) and self.mode else 0
            o=(bank%max(1,len(self.rom)//0x4000))*0x4000+a
            return self.rom[o] if o<len(self.rom) else 0xFF
        if a<0x8000:
            bank=self.rom_bank%max(1,len(self.rom)//0x4000); bank=bank or 1; o=bank*0x4000+a-0x4000
            return self.rom[o] if o<len(self.rom) else 0xFF
        if 0xA000<=a<0xC000 and self.ram_enabled:
            if self.kind in (0x0F,0x10,0x12,0x13) and 8<=self.rtc_select<=12:return self.rtc[self.rtc_select-8]
            if not self.ram:return 0xFF
            bank=self.ram_bank%max(1,len(self.ram)//0x2000); return self.ram[(bank*0x2000+a-0xA000)%len(self.ram)]
        return 0xFF
    def write(self,a,v):
        v&=255;k=self.kind
        if k in (1,2,3):
            if a<0x2000:self.ram_enabled=(v&15)==10
            elif a<0x4000:self.rom_bank=(self.rom_bank&0x60)|(v&31 or 1)
            elif a<0x6000:
                self.mbc1_hi=v&3
                if self.mode:self.ram_bank=self.mbc1_hi
                else:self.rom_bank=(self.rom_bank&31)|(self.mbc1_hi<<5)
            elif a<0x8000:self.mode=v&1
        elif k in (5,6):
            if a<0x4000:
                if a&0x100:self.rom_bank=v&15 or 1
                else:self.ram_enabled=(v&15)==10
        elif k in (0x0F,0x10,0x11,0x12,0x13):
            if a<0x2000:self.ram_enabled=(v&15)==10
            elif a<0x4000:self.rom_bank=v&0x7F or 1
            elif a<0x6000:
                if v<=3:self.ram_bank=v;self.rtc_select=0
                elif 8<=v<=12:self.rtc_select=v
        elif 0x19<=k<=0x1E:
            if a<0x2000:self.ram_enabled=(v&15)==10
            elif a<0x3000:self.rom_bank=(self.rom_bank&0x100)|v
            elif a<0x4000:self.rom_bank=(self.rom_bank&255)|((v&1)<<8)
            elif a<0x6000:self.ram_bank=v&15
        if 0xA000<=a<0xC000 and self.ram_enabled:
            if k in (0x0F,0x10,0x12,0x13) and 8<=self.rtc_select<=12:self.rtc[self.rtc_select-8]=v
            elif self.ram:
                bank=self.ram_bank%max(1,len(self.ram)//0x2000);self.ram[(bank*0x2000+a-0xA000)%len(self.ram)]=v

class Bus:
    def __init__(self,cart,input_provider=None):
        self.cart=cart;self.vram=bytearray(0x2000);self.wram=bytearray(0x2000);self.oam=bytearray(0xA0);self.hram=bytearray(0x7F);self.io=bytearray(0x80)
        self.ie=0;self.iflag=0xE1;self.div_counter=0;self.timer_counter=0;self.input_provider=input_provider;self.joyp_select=0x30
        self.io[0x40]=0x91;self.io[0x47]=0xFC;self.io[0x48]=0xFF;self.io[0x49]=0xFF
    def read8(self,a):
        a&=0xFFFF
        if a<0x8000 or 0xA000<=a<0xC000:return self.cart.read(a)
        if a<0xA000:return self.vram[a-0x8000]
        if a<0xE000:return self.wram[a-0xC000]
        if a<0xFE00:return self.wram[a-0xE000]
        if a<0xFEA0:return self.oam[a-0xFE00]
        if a<0xFF00:return 0xFF
        if a==0xFF00:
            state=self.input_provider() if self.input_provider else 0xFF;low=15
            if not(self.joyp_select&0x10):low&=state&15
            if not(self.joyp_select&0x20):low&=(state>>4)&15
            return 0xC0|self.joyp_select|low
        if a==0xFF04:return (self.div_counter>>8)&255
        if a==0xFF0F:return self.iflag|0xE0
        if a<0xFF80:return self.io[a-0xFF00]
        if a<0xFFFF:return self.hram[a-0xFF80]
        return self.ie
    def write8(self,a,v):
        a&=0xFFFF;v&=255
        if a<0x8000 or 0xA000<=a<0xC000:self.cart.write(a,v);return
        if a<0xA000:self.vram[a-0x8000]=v;return
        if a<0xE000:self.wram[a-0xC000]=v;return
        if a<0xFE00:self.wram[a-0xE000]=v;return
        if a<0xFEA0:self.oam[a-0xFE00]=v;return
        if a<0xFF00:return
        if a==0xFF00:self.joyp_select=v&0x30;return
        if a==0xFF04:self.div_counter=0;return
        if a==0xFF0F:self.iflag=v&31;return
        if a==0xFF46:
            base=v<<8
            for i in range(0xA0):self.oam[i]=self.read8(base+i)
            self.io[0x46]=v;return
        if a<0xFF80:self.io[a-0xFF00]=v;return
        if a<0xFFFF:self.hram[a-0xFF80]=v;return
        self.ie=v
    def read16(self,a):return self.read8(a)|(self.read8(a+1)<<8)
    def write16(self,a,v):self.write8(a,v);self.write8(a+1,v>>8)
    def tick(self,c):
        self.div_counter=(self.div_counter+c)&0xFFFF;tac=self.io[7]
        if tac&4:
            periods=(1024,16,64,256);self.timer_counter+=c;p=periods[tac&3]
            while self.timer_counter>=p:
                self.timer_counter-=p;t=self.io[5]+1
                if t>255:self.io[5]=self.io[6];self.iflag|=4
                else:self.io[5]=t

class CPU:
    def __init__(self,bus):
        self.b=bus;self.a=1;self.f=0xB0;self.breg=0;self.c=0x13;self.d=0;self.e=0xD8;self.h=1;self.l=0x4D;self.sp=0xFFFE;self.pc=0x100
        self.ime=False;self.ime_pending=False;self.halted=False;self.stopped=False;self.cycles=0
    def af(self):return(self.a<<8)|self.f
    def bc(self):return(self.breg<<8)|self.c
    def de(self):return(self.d<<8)|self.e
    def hl(self):return(self.h<<8)|self.l
    def set_af(self,v):self.a=(v>>8)&255;self.f=v&0xF0
    def set_bc(self,v):self.breg=(v>>8)&255;self.c=v&255
    def set_de(self,v):self.d=(v>>8)&255;self.e=v&255
    def set_hl(self,v):self.h=(v>>8)&255;self.l=v&255
    def fetch8(self):v=self.b.read8(self.pc);self.pc=(self.pc+1)&0xFFFF;return v
    def fetch16(self):lo=self.fetch8();return lo|(self.fetch8()<<8)
    def push(self,v):self.sp=(self.sp-1)&0xFFFF;self.b.write8(self.sp,v>>8);self.sp=(self.sp-1)&0xFFFF;self.b.write8(self.sp,v)
    def pop(self):lo=self.b.read8(self.sp);self.sp=(self.sp+1)&0xFFFF;hi=self.b.read8(self.sp);self.sp=(self.sp+1)&0xFFFF;return lo|(hi<<8)
    def _get_r(self,i):
        return (self.breg,self.c,self.d,self.e,self.h,self.l,self.b.read8(self.hl()),self.a)[i]
    def _set_r(self,i,v):
        v&=255
        if i==0:self.breg=v
        elif i==1:self.c=v
        elif i==2:self.d=v
        elif i==3:self.e=v
        elif i==4:self.h=v
        elif i==5:self.l=v
        elif i==6:self.b.write8(self.hl(),v)
        else:self.a=v
    def _inc8(self,v):r=(v+1)&255;c=self.f&FLAG_C;self.f=c|(FLAG_Z if r==0 else 0)|(FLAG_H if(v&15)==15 else 0);return r
    def _dec8(self,v):r=(v-1)&255;c=self.f&FLAG_C;self.f=c|FLAG_N|(FLAG_Z if r==0 else 0)|(FLAG_H if(v&15)==0 else 0);return r
    def _add(self,v,carry=0):
        c=1 if carry and self.f&FLAG_C else 0;s=self.a+v+c;r=s&255;self.f=(FLAG_Z if r==0 else 0)|(FLAG_H if((self.a&15)+(v&15)+c)>15 else 0)|(FLAG_C if s>255 else 0);self.a=r
    def _sub(self,v,carry=0):
        c=1 if carry and self.f&FLAG_C else 0;s=self.a-v-c;r=s&255;self.f=FLAG_N|(FLAG_Z if r==0 else 0)|(FLAG_H if(self.a&15)<((v&15)+c) else 0)|(FLAG_C if s<0 else 0);self.a=r
    def _and(self,v):self.a&=v;self.f=(FLAG_Z if self.a==0 else 0)|FLAG_H
    def _xor(self,v):self.a^=v;self.f=FLAG_Z if self.a==0 else 0
    def _or(self,v):self.a|=v;self.f=FLAG_Z if self.a==0 else 0
    def _cp(self,v):s=self.a-v;r=s&255;self.f=FLAG_N|(FLAG_Z if r==0 else 0)|(FLAG_H if(self.a&15)<(v&15) else 0)|(FLAG_C if s<0 else 0)
    def _condition(self,i):return((self.f&FLAG_Z)==0,(self.f&FLAG_Z)!=0,(self.f&FLAG_C)==0,(self.f&FLAG_C)!=0)[i]
    def _service_interrupt(self):
        p=self.b.ie&self.b.iflag&31
        if not p:return 0
        self.halted=False
        if not self.ime:return 0
        self.ime=False;bit=0
        while not(p&(1<<bit)):bit+=1
        self.b.iflag&=~(1<<bit);self.push(self.pc);self.pc=(0x40,0x48,0x50,0x58,0x60)[bit];return 20
    def step(self):
        c=self._service_interrupt()
        if c:self.b.tick(c);self.cycles+=c;return c
        if self.halted:self.b.tick(4);self.cycles+=4;return 4
        op=self.fetch8();c=self._exec(op)
        if self.ime_pending:self.ime=True;self.ime_pending=False
        self.b.tick(c);self.cycles+=c;return c
    def _exec(self,op):
        if 0x40<=op<=0x7F:
            if op==0x76:self.halted=True;return 4
            d=(op>>3)&7;s=op&7;self._set_r(d,self._get_r(s));return 8 if d==6 or s==6 else 4
        if 0x80<=op<=0xBF:
            g=(op>>3)&7;v=self._get_r(op&7);(self._add,lambda x:self._add(x,1),self._sub,lambda x:self._sub(x,1),self._and,self._xor,self._or,self._cp)[g](v);return 8 if(op&7)==6 else 4
        if op<0x40:
            if op&7==4:r=(op>>3)&7;self._set_r(r,self._inc8(self._get_r(r)));return 12 if r==6 else 4
            if op&7==5:r=(op>>3)&7;self._set_r(r,self._dec8(self._get_r(r)));return 12 if r==6 else 4
            if op&7==6:r=(op>>3)&7;self._set_r(r,self.fetch8());return 12 if r==6 else 8
        if op in(1,0x11,0x21,0x31):v=self.fetch16();(self.set_bc,self.set_de,self.set_hl,lambda x:setattr(self,'sp',x))[op>>4](v);return 12
        if op in(3,0x13,0x23,0x33):i=op>>4;v=((self.bc(),self.de(),self.hl(),self.sp)[i]+1)&0xFFFF;(self.set_bc,self.set_de,self.set_hl,lambda x:setattr(self,'sp',x))[i](v);return 8
        if op in(0x0B,0x1B,0x2B,0x3B):i=op>>4;v=((self.bc(),self.de(),self.hl(),self.sp)[i]-1)&0xFFFF;(self.set_bc,self.set_de,self.set_hl,lambda x:setattr(self,'sp',x))[i](v);return 8
        if op in(9,0x19,0x29,0x39):v=(self.bc(),self.de(),self.hl(),self.sp)[op>>4];h=self.hl();s=h+v;self.f=(self.f&FLAG_Z)|(FLAG_H if((h&0xFFF)+(v&0xFFF))>0xFFF else 0)|(FLAG_C if s>0xFFFF else 0);self.set_hl(s);return 8
        if op==0:return 4
        if op==2:self.b.write8(self.bc(),self.a);return 8
        if op==0x0A:self.a=self.b.read8(self.bc());return 8
        if op==0x12:self.b.write8(self.de(),self.a);return 8
        if op==0x1A:self.a=self.b.read8(self.de());return 8
        if op==0x22:self.b.write8(self.hl(),self.a);self.set_hl(self.hl()+1);return 8
        if op==0x2A:self.a=self.b.read8(self.hl());self.set_hl(self.hl()+1);return 8
        if op==0x32:self.b.write8(self.hl(),self.a);self.set_hl(self.hl()-1);return 8
        if op==0x3A:self.a=self.b.read8(self.hl());self.set_hl(self.hl()-1);return 8
        if op==8:self.b.write16(self.fetch16(),self.sp);return 20
        if op==0x10:self.stopped=True;self.fetch8();return 4
        if op in(7,0x0F,0x17,0x1F):
            old=self.a;through=op in(0x17,0x1F);left=op in(7,0x17);cin=1 if through and self.f&FLAG_C else 0
            if left:r=((old<<1)|cin)&255;c=old>>7
            else:r=(old>>1)|(cin<<7);c=old&1
            self.a=r;self.f=FLAG_C if c else 0;return 4
        if op==0x27:
            a=self.a;adj=0;c=bool(self.f&FLAG_C)
            if not self.f&FLAG_N:
                if c or a>0x99:adj|=0x60;c=True
                if self.f&FLAG_H or(a&15)>9:adj|=6
                a=(a+adj)&255
            else:
                if c:adj|=0x60
                if self.f&FLAG_H:adj|=6
                a=(a-adj)&255
            self.a=a;self.f=(self.f&FLAG_N)|(FLAG_C if c else 0)|(FLAG_Z if a==0 else 0);return 4
        if op==0x2F:self.a^=255;self.f=(self.f&(FLAG_Z|FLAG_C))|FLAG_N|FLAG_H;return 4
        if op==0x37:self.f=(self.f&FLAG_Z)|FLAG_C;return 4
        if op==0x3F:self.f=(self.f&FLAG_Z)|(0 if self.f&FLAG_C else FLAG_C);return 4
        if op==0x18:self.pc=(self.pc+_s8(self.fetch8()))&0xFFFF;return 12
        if op in(0x20,0x28,0x30,0x38):off=_s8(self.fetch8());cond=self._condition((op-0x20)//8);self.pc=(self.pc+off)&0xFFFF if cond else self.pc;return 12 if cond else 8
        if op==0xC3:self.pc=self.fetch16();return 16
        if op==0xE9:self.pc=self.hl();return 4
        if op in(0xC2,0xCA,0xD2,0xDA):a=self.fetch16();cond=self._condition((op-0xC2)//8);self.pc=a if cond else self.pc;return 16 if cond else 12
        if op==0xCD:a=self.fetch16();self.push(self.pc);self.pc=a;return 24
        if op in(0xC4,0xCC,0xD4,0xDC):a=self.fetch16();cond=self._condition((op-0xC4)//8);self.push(self.pc) if cond else None;self.pc=a if cond else self.pc;return 24 if cond else 12
        if op==0xC9:self.pc=self.pop();return 16
        if op==0xD9:self.pc=self.pop();self.ime=True;return 16
        if op in(0xC0,0xC8,0xD0,0xD8):
            if self._condition((op-0xC0)//8):self.pc=self.pop();return 20
            return 8
        if op&0xC7==0xC7:self.push(self.pc);self.pc=op&0x38;return 16
        if op in(0xC1,0xD1,0xE1,0xF1):v=self.pop();(self.set_bc,self.set_de,self.set_hl,self.set_af)[(op-0xC1)//16](v);return 12
        if op in(0xC5,0xD5,0xE5,0xF5):v=(self.bc(),self.de(),self.hl(),self.af())[(op-0xC5)//16];self.push(v);return 16
        if op in(0xC6,0xCE,0xD6,0xDE,0xE6,0xEE,0xF6,0xFE):v=self.fetch8();g=(op-0xC6)//8;(self._add,lambda x:self._add(x,1),self._sub,lambda x:self._sub(x,1),self._and,self._xor,self._or,self._cp)[g](v);return 8
        if op==0xE0:self.b.write8(0xFF00+self.fetch8(),self.a);return 12
        if op==0xF0:self.a=self.b.read8(0xFF00+self.fetch8());return 12
        if op==0xE2:self.b.write8(0xFF00+self.c,self.a);return 8
        if op==0xF2:self.a=self.b.read8(0xFF00+self.c);return 8
        if op==0xEA:self.b.write8(self.fetch16(),self.a);return 16
        if op==0xFA:self.a=self.b.read8(self.fetch16());return 16
        if op==0xE8:n=_s8(self.fetch8());sp=self.sp;r=(sp+n)&0xFFFF;self.f=(FLAG_H if((sp&15)+(n&15))>15 else 0)|(FLAG_C if((sp&255)+(n&255))>255 else 0);self.sp=r;return 16
        if op==0xF8:n=_s8(self.fetch8());sp=self.sp;r=(sp+n)&0xFFFF;self.f=(FLAG_H if((sp&15)+(n&15))>15 else 0)|(FLAG_C if((sp&255)+(n&255))>255 else 0);self.set_hl(r);return 12
        if op==0xF9:self.sp=self.hl();return 8
        if op==0xF3:self.ime=False;self.ime_pending=False;return 4
        if op==0xFB:self.ime_pending=True;return 4
        if op==0xCB:return self._cb(self.fetch8())
        return 4
    def _cb(self,op):
        r=op&7;group=op>>6;bit=(op>>3)&7;v=self._get_r(r);cost=16 if r==6 else 8
        if group==0:
            kind=(op>>3)&7;c=0
            if kind==0:c=v>>7;v=((v<<1)|c)&255
            elif kind==1:c=v&1;v=(v>>1)|(c<<7)
            elif kind==2:c=v>>7;v=((v<<1)|(1 if self.f&FLAG_C else 0))&255
            elif kind==3:c=v&1;v=(v>>1)|((1 if self.f&FLAG_C else 0)<<7)
            elif kind==4:c=v>>7;v=(v<<1)&255
            elif kind==5:c=v&1;v=(v>>1)|(v&0x80)
            elif kind==6:v=((v<<4)|(v>>4))&255
            else:c=v&1;v>>=1
            self._set_r(r,v);self.f=(FLAG_Z if v==0 else 0)|(FLAG_C if c else 0);return cost
        if group==1:self.f=(self.f&FLAG_C)|FLAG_H|(FLAG_Z if not(v&(1<<bit)) else 0);return 12 if r==6 else 8
        if group==2:self._set_r(r,v&~(1<<bit));return cost
        self._set_r(r,v|(1<<bit));return cost

class PPU:
    def __init__(self,bus,line_sink):self.b=bus;self.line_sink=line_sink;self.dot=0;self.ly=0;self.frame=0;self.line=bytearray(320);self.colors=bytearray(160)
    def tick(self,c):
        if not self.b.io[0x40]&0x80:return
        self.dot+=c
        while self.dot>=456:
            self.dot-=456
            if self.ly<144:self.render_line(self.ly)
            self.ly+=1
            if self.ly==144:self.b.iflag|=1
            if self.ly>=154:self.ly=0;self.frame+=1
            self.b.io[0x44]=self.ly;stat=self.b.io[0x41]
            if self.ly==self.b.io[0x45]:stat|=4;self.b.iflag|=2 if stat&0x40 else 0
            else:stat&=~4
            self.b.io[0x41]=stat
    def _shade(self,p,i):return DMG_PALETTE[(p>>(i*2))&3]
    @micropython.native
    def render_line(self,y):
        lcdc=self.b.io[0x40];v=self.b.vram;scy=self.b.io[0x42];scx=self.b.io[0x43];wy=self.b.io[0x4A];wx=self.b.io[0x4B]-7
        bg=0x1C00 if lcdc&8 else 0x1800;win=0x1C00 if lcdc&0x40 else 0x1800;unsigned=bool(lcdc&0x10);pal=self.b.io[0x47]
        for x in range(160):
            uw=(lcdc&0x20) and y>=wy and x>=wx;px=x-wx if uw else(x+scx)&255;py=y-wy if uw else(y+scy)&255;mb=win if uw else bg
            t=v[mb+(py>>3)*32+(px>>3)];ta=t*16 if unsigned else 0x1000+_s8(t)*16;row=ta+(py&7)*2;bit=7-(px&7);ci=((v[row]>>bit)&1)|(((v[row+1]>>bit)&1)<<1)
            self.colors[x]=ci;col=self._shade(pal,ci);o=x*2;self.line[o]=col>>8;self.line[o+1]=col&255
        if lcdc&2:
            height=16 if lcdc&4 else 8;count=0
            for i in range(40):
                sy=self.b.oam[i*4]-16;sx=self.b.oam[i*4+1]-8
                if not(sy<=y<sy+height):continue
                count+=1
                if count>10:break
                t=self.b.oam[i*4+2];fl=self.b.oam[i*4+3];row=y-sy
                if fl&0x40:row=height-1-row
                if height==16:t&=0xFE
                a=t*16+row*2;lo=v[a];hi=v[a+1];p=self.b.io[0x49 if fl&0x10 else 0x48]
                for q in range(8):
                    bit=q if fl&0x20 else 7-q;ci=((lo>>bit)&1)|(((hi>>bit)&1)<<1);x=sx+q
                    if ci and 0<=x<160 and not(fl&0x80 and self.colors[x]):col=self._shade(p,ci);o=x*2;self.line[o]=col>>8;self.line[o+1]=col&255
        self.line_sink(y,self.line)

class GameBoy:
    def __init__(self,rom,line_sink,input_provider=None,save_path=None):self.cart=Cartridge(rom,save_path);self.bus=Bus(self.cart,input_provider);self.cpu=CPU(self.bus);self.ppu=PPU(self.bus,line_sink)
    def run_frame(self):
        target=self.ppu.frame+1
        while self.ppu.frame<target:c=self.cpu.step();self.ppu.tick(c)
    def save(self):self.cart.save()
