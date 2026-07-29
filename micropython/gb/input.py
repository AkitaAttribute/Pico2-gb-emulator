from machine import Pin
class Buttons:
    def __init__(self,pins=(18,20,21,19,17,16,22,26)):
        self.pins=[Pin(p,Pin.IN,Pin.PULL_UP) for p in pins]
    def read(self):
        v=0xFF
        for i,p in enumerate(self.pins):
            if not p.value():v&=~(1<<i)
        return v
