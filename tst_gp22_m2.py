# setup
from machine import bitstream, Pin, SoftSPI, SPI
from time import sleep_us
import esp32
import gp22

#
# GP22   ESP32             4-wire SPI
# SSN -- 15                CS
# SCK -- 2                 CLK
# SO  -- 22                MISO
# SI  -- 17                MOSI
# 
# RTN -- 21                RST for GP22, high to enable the chip
#
#                          polarity=0, phase=1, MSB
#
# INT -- 13                interrupt 
#
# DIS -- 12                enable/disable tof

# config 4-wire SPI
spi = SoftSPI( sck=Pin(2), mosi=Pin(17), miso=Pin(22), polarity=0, phase=1, firstbit=SPI.MSB )
spi.init()
cs = Pin(15, mode=Pin.OUT, value=1)
# reset pin
rst = Pin(21, mode=Pin.OUT, value=1) # high enable gp22
dis = Pin(12, mode=Pin.OUT, value=1) # high enable tof
# config interrupt
pint = Pin(13, Pin.IN, Pin.PULL_UP)

# config esp32 rmt pulse generator in pin32
rmt1 = esp32.RMT(0, pin=Pin(32), clock_div=1, idle_level=0)
# r.write_pulses((1, 1), 0)   # two pulses
# r.write_pulses((10, 1, 10), 0)
# r.write_pulses((20, 1, 20), 0)
# r.write_pulses((20, 1, 20, 1, 20, 1, 20, 1, 20), 0)  # 5 pulses

## init. gp22 chips
tdc1 = gp22.GP22(spi, cs, rst, pint)
tdc1.reset()

## waiting time measurement wire up
#GP32(esp32) -> STA(GP22) -> SP1(GP22)

## tof in mode 2
def cfg_m2_fwt(tdc):
    """Configre gp22 to mode 2, 1 ch"""
    ## reg0
    # time unit = 1/4M = 0.25uS
    tdc.reg0 = b'\x00\x04\x28\x00'
    tdc.writeReg(0, tdc.reg0)
    ## reg1
    tdc.reg1 = b'\x21\x43\x00\x00'  # 2 pulses + START pulses
    #tdc.reg1 = b'\x21\x42\x00\x00'  # 1 pulses + START pulses
    
    tdc.writeReg(1, tdc.reg1)
    ## reg2: interrupt source, edge sensitities and DELVAL1
    tdc.reg2 = b'\xe0\x00\x00\x00'
    tdc.writeReg(2, tdc.reg2)
    tdc.parse_reg2()
    ## reg3 : mode 2 and DELVAL2, 
    #tdc1.reg3 = b'\x00\x00\x00\x00'
    # EN_AUTOCALC_MB2 = 1, SEL_TIMO_MB2 = 3 4096 uS
    tdc.reg3 = b'\x98\x00\x00\x00'
    tdc.writeReg(3, tdc.reg3)
    tdc.parse_reg3()
    ## reg4: DELVAL3
    tdc.reg4 = b'\x20\x00\x00\x00'    
    tdc.writeReg(4, tdc.reg4)
    tdc.parse_reg4()
    ## reg5: pulse
    tdc.reg5 = b'\x00\x00\x00\x00'
    tdc.writeReg(5, tdc.reg5)
    tdc.parse_reg5()
    ## reg6: analogy frontend, do not use here
    tdc.reg6 = b'\x00\x00\x00\x00'
    tdc.writeReg(6, tdc.reg6)

# perform a single measurement for waiting time #1: stop1 - start
#                                  and waiting time #2: stop2 - stop1
# mode 2
# input:
# tdc: tdc device
# rmt: rmt device
# return value
# itmax: timeout for a single measurement
# tof : TOF in us
# err : 0 for no error, 1 for error
def fwt_m2(tdc, trig, itmax):
    tdc.init_op()   # init the tdc
    trig.write_pulses((1, 23, 14, 10, 35, 20), 0)  # 3 pulses, separated from each other by 12.5 * (23 + 14) = 462.5ns, 12.5 * (10 + 35) = 562.5ns
    # wait until tdc interrupt occurs
    it = 0
    while (not tdc.intflag) and (it <= itmax):
        sleep_us(1)
        it += 1
    # it > itmax for interrupt timeout
    err_tdc = tdc.st_err()    # non zero for error
    alu_op = tdc.alu_op()     # 1 ~ 4 for non error
    
    if ( it < itmax ) and ( int(err_tdc) == 0 ) and alu_op > 0:
        err = 0  # no error, let us calculate tof
        # real all results, in units of 1/4MHz
        dat = tdc.readReg(0)
        tof1 = gp22.bytes_to_fixedfloat(dat) * 0.25  # 1.STOP1 - START, first passage time
        wt1 = tof1
        dat = tdc.readReg(1)
        tof2 = gp22.bytes_to_fixedfloat(dat) * 0.25  # 2.STOP1 - START, waiting time
        wt2 = tof2 - tof1
    else:
        err = 1
        wt1 = 0.0
        wt2 = 0.0

    return err, wt1, wt2


## run the following code for full tof measurement
cfg_m2_fwt(tdc1)
itmax1 = 10  # timeout (uS)
# wt1 ~ 464nS, wt2 ~ 561nS
err1, wt1, wt2 = fwt_m2(tdc1, rmt1, itmax1)
print(f'wt1 = {wt1} uS')
print(f'wt2 = {wt2} uS')
