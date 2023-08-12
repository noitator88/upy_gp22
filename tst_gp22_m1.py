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

## init. gp22 device
tdc1 = gp22.GP22(spi, cs, rst, pint)
tdc1.reset()

## waiting time measurement wire up
#GP32(esp32) -> STA(GP22) -> SP1(GP22)

## setup gp22 for waiting time measurment in ch1
def cfg_m1_fwt(tdc):
    """Configre gp22 to mode 1
        Measure the first passage time in ch1
        Disable ch2
    """
    ## reg0
    # disable fire pulse generator
    # number of periods used for calibrating the ceramic resonator: 2 periods = 61.035 µs
    # predivider for CLKHS = 4 : give time units 1.0/( 4M/4 ) = 1uS, with 4M high-speed crystal oscill
    # Oscillator continuously on
    # Enables calibration calculation in the ALU
    # Enables auto-calibration for each TDC run
    # detect rising edge in stop1, stop 2 and start    
    tdc.reg0 = b'\x00\x24\x20\x00'
    tdc.writeReg(0, tdc.reg0)
    ## reg1
    # HIT2 = 0 for START
    # HIT1 = 1 for 1.STOP1
    # HITN2 = 0 to disable stop2
    # HITN1 = 1 : expect 1 pulse in ch1

    tdc.reg1 = b'\x01\x41\x00\x00'  # HITN1 = 1, calculate STOP1 - START
    #tdc.reg1 = b'\x01\x42\x00\x00'  # HITN1 = 2, calculate STOP1 - START
    #tdc.reg1 = b'\x12\x42\x00\x00'  # HITN1 = 2, calculate 2.STOP1 - 1.STOP1    
    #tdc1.reg1 = b'\x19\x64\x00\x00' # 2chs, 4 pulses each
    
    tdc.writeReg(1, tdc.reg1)
    ## reg2: interrupt source, edge sensitities and DELVAL1
    tdc.reg2 = b'\xe0\x00\x00\x00'
    tdc.writeReg(2, tdc.reg2)
    tdc.parse_reg2()
    ## reg3 : mode 2 and DELVAL2
    tdc.reg3 = b'\x00\x00\x00\x00'
    tdc.writeReg(3, tdc.reg3)
    tdc.parse_reg3()
    ## reg4: DELVAL3
    tdc.reg4 = b'\x20\x00\x00\x00'    
    tdc.writeReg(4, tdc.reg4)
    tdc.parse_reg4()
    ## reg5: pulse
    tdc.reg5 = b'\x10\x00\x00\x00'
    tdc.writeReg(5, tdc.reg5)
    tdc.parse_reg5()
    ## reg6: analogy frontend, do not use here
    tdc.reg6 = b'\x00\x00\x00\x00'
    tdc.writeReg(6, tdc.reg6)
    
# perform a single measurement for waiting time: stop1 - start
# mode 1
# input:
# tdc: tdc device
# rmt: rmt device, which sends the test pulses
# return value
# itmax: timeout (uS)
# tof : TOF in us
# err : 0 for no error, 1 for error
def fwt_m1(tdc, trig, itmax):
    tdc.init_op()   # init the tdc
    trig.write_pulses((1, 23, 14, 10), 0)  # 2 pulses, separated from each other by 12.5 * (23 + 14) = 462.5ns
    # wait until tdc interrupt occurs
    it = 0
    while (not tdc.intflag) and (it <= itmax):
        sleep_us(1)
        it += 1
    # it > itmax for interrupt timeout
    err_tdc = tdc.st_err()    # non zero for error
    alu_op = tdc.alu_op()     # 1 ~ 4 for non error
    
    if ( it < itmax ) and ( int(err_tdc) == 0 ) and alu_op > 0:
        err = 0  # no error, let us read first passage time = STOP1 - START
        dat = tdc.readReg(alu_op - 1)
        fpt = gp22.bytes_to_fixedfloat(dat) * 1.0 # in time unit of 1.0uS
    else:
        err = 1
        fpt = 0.0

    return err, fpt


## run the following code for tof measurement test
cfg_m1_fwt(tdc1)
itmax1 = 10  # timeout (uS)
# This returns ~ 454ns, which is smaller than 462.5ns.
# Possibly due to the imperfact profile of the voltage pulses and inaccuracy of the chips clock source
err1, fwt1 = fwt_m1(tdc1, rmt1, itmax1)
print(f'fwt1 = {fwt1} uS')

