import binascii
from machine import Pin
from time import sleep_us
# Error buffer for inside ISRs, see https://docs.micropython.org/en/latest/reference/isr_rules.html
import micropython
micropython.alloc_emergency_exception_buf(100)

# convert bytes to float, bytes correspond to 32bits fixed point float (Q-format)
# nn must be 32
def bytes_to_fixedfloat(byte_lst):
    bin_lst = bytes_to_bins(byte_lst)
    nn = len(bin_lst)
    fb = 0.0
    for n in range(nn):
        nb = n - 16
        b1 = int(bin_lst[nn - n - 1])
        fb += b1 * 2 ** nb
    return fb

# enum in python
# https://stackoverflow.com/questions/36932/how-can-i-represent-an-enum-in-python
# https://github.com/micropython/micropython-lib/issues/269
def enum(**enums: int):
    return type('Enum', (), enums)

## convert a byte array to bin list
def bytes_to_bins(byte_lst):
    return ''.join( f'{byte:0>8b}' for byte in byte_lst )

# read the n-th bit
def get_bin(byte_lst, n):
    bin_lst = bytes_to_bins(byte_lst)
    nn = len(bin_lst)
    return int(bin_lst[nn - n - 1])

## class for GP22 manipulation
class GP22():
    """
    Micropython TDC GP22 driver
    SPI interface
    """
    
    OPCODE = enum(
        OPCODE_WRITE_ADDRESS        = b'\x80', # 3 LSB are the address to write
        OPCODE_READ_ADDRESS         = b'\xB0', # 3 LSB are the address to read
        OPCODE_READ_ID              = b'\xB7',
        OPCODE_INIT                 = b'\x70',
        OPCODE_POWER_ON_RESET       = b'\x50',
        OPCODE_START_TOF            = b'\x01',
        OPCODE_START_CAL_RESONATOR  = b'\x03',
        OPCODE_START_CAL_TDC        = b'\x04',
        OPCODE_START_TOF_RESTART    = b'\x05'
    )

    intflag = False         # if int has been triggered
    stat = b'\x00\x00'      # stat register of tdc gp22
    # spi, cs, rst, pint    for tdc gp22 pinout connection
    reg0 = b'\x00\x00\x00\x00'
    reg1 = b'\x00\x00\x00\x00'
    reg2 = b'\x00\x00\x00\x00'
    reg3 = b'\x00\x00\x00\x00'
    reg4 = b'\x00\x00\x00\x00'
    reg5 = b'\x00\x00\x00\x00'
    reg6 = b'\x00\x00\x00\x00'
    
    def __init__(self, spi, cs, rst, pint):
        # set up 4-wire spi
        self.spi = spi
        self.cs  = cs
        # rstn pin for hard reset
        self.rst = rst
        # interrupt pin
        self.pint_ref = pint
        # trick for allocating the bound method of a class to isr
        self.pisr_ref = self.pisr
        # set irq for int pin
        pint.irq(trigger=Pin.IRQ_FALLING, handler=self.cb)

    def pisr(self, _):
        self.stat = self.readReg(4)
        self.intflag = True
        #print("Int triggered.")          # debug 
    
    def st_err(self):
        str_st = bytes_to_bins(self.stat)
        return str_st[0:7]

    def hit_ch2(self):
        """num. of hits in ch 2"""
        str_st = bytes_to_bins(self.stat)
        return int( str_st[7:10], 2)
    
    def hit_ch1(self):
        """num. of hits in ch 1"""
        str_st = bytes_to_bins(self.stat)
        return int( str_st[10:13], 2)

    def alu_op(self):
        """ALU operation pointer"""
        str_st = bytes_to_bins(self.stat)
        return int( str_st[13:16], 2)

    def cb(self, p):
        # Passing self.bar would cause allocation.
        micropython.schedule(self.pisr_ref, 0)        
    
    def reset(self):
        """
        Ref p2-8 fig2-5 for reset timing via rstn pin
        """
        ## hard reset via rstn pin
        self.rst(0)
        sleep_us(1)      # minimum length is 50ns
        self.rst(1)
        sleep_us(500)    # analog section is ready after 500us
        ## soft reset via spi command
        self.writeBytes(self.OPCODE.OPCODE_POWER_ON_RESET)
        
    def init_op(self):
        """Initialize measurement"""
        self.writeBytes( self.OPCODE.OPCODE_INIT )
        
    def writeBytes(self, opcode, dat=b'\x00'):
        """
        write opcode first, then write bytes in dat
        opcode: byte
        dat: byte or bytearray

        """
        self.cs(0)
        self.spi.write(opcode)
        self.spi.write(dat)
        self.cs(1)

    def writeReg(self, n, dat):
        """
        Write dat to reg n (n = 0 ~ 6)
        n: int
        dat: byte or bytearray
        """
        opcode = bytes([ ord(self.OPCODE.OPCODE_WRITE_ADDRESS) + n ])
        self.writeBytes(opcode, dat)

    def readBytes(self, opcode, n):
        """
        write opcode, then read n bytes into dat
        opcode: byte
        n : inter
        """
        self.cs(0)
        self.spi.write(opcode)
        dat = self.spi.read(n)
        self.cs(1)
        
        return dat

    def readReg(self, n):
        """
        Read k bytes from reg n (n = 0 ~ 4, 5, 8)
        n: int
        k: length
        return bytearray
        """
        opcode = bytes([ ord(self.OPCODE.OPCODE_READ_ADDRESS) + n ])
        if n == 0 or n == 1 or n == 2 or n == 3:
            k = 4  # 32 bits
        elif n == 4:
            k = 2  # 16 bits
        else:
            k = 1  # 8 bits
        dat = self.readBytes(opcode, k)
        return dat
    
    def parse_reg0(self):
        binx = bytes_to_bins(self.reg0)
        str = ''
        i = 31
        for b1 in binx:
            str += b1
            if i == 28:
                str += " | ANZ_FIRE \n"
            if i == 24:
                str += " | DIV_FIRE \n"
            if i == 22:
                str += " | ANZ_PER_CALRES \n"
            if i == 20:
                str += " | DIV_CLKHS \n"
            if i == 18:
                str += " | START_CLKHS \n"
            if i == 17:
                str += " | ANZ_PORT \n"
            if i == 16:
                str += " | TCYCLE \n"
            if i == 15:
                str += " | ANZ_FAKE \n"
            if i == 14:
                str += " | SEL_ECLK_TMP \n"
            if i == 13:
                str += " | CALIBRATE \n"
            if i == 12:
                str += " | NO_CAL_AUTO \n"
            if i == 11:
                str += " | MESSB2 \n"
            if i == 10:
                str += " | NEG_STOP2 \n"
            if i == 9:
                str += " | NEG_STOP1 \n"
            if i == 8:
                str += " | NEG_START \n"
            i -= 1
            
        str += " | ID0"
        return str

    def parse_reg1(self):
        binx = bytes_to_bins(self.reg1)
        str = ''
        i = 31
        for b1 in binx:
            str += b1
            if i == 28:
                str += " | HIT2 \n"
            if i == 24:
                str += " | HIT1 \n"
            if i == 23:
                str += " | EN_FAST_INIT \n"
            if i == 22:
                str += " | k.d. \n"
            if i == 19:
                str += " | HITIN2 \n"
            if i == 16:
                str += " | HITIN1 \n"
            if i == 15:
                str += " | CURR32K \n"
            if i == 14:
                str += " | SEL_START_FIRE \n"
            if i == 11:
                str += " | SEL_TSTO2 \n"
            if i == 8:
                str += " | SEL_TSTO1 \n"            
            i -= 1
            
        str += " | ID1"
        return str

    def parse_reg2(self):
        binx = bytes_to_bins(self.reg2)
        str = ''
        i = 31
        for b1 in binx:
            str += b1
            if i == 29:
                str += " | EN_INT \n"
            if i == 28:
                str += " | RFEDGE2 \n"
            if i == 27:
                str += " | RFEDGE1 \n"
            if i == 8:
                str += " | DELVAL1 \n"            
            i -= 1
            
        str += " | ID2"
        return str

    def parse_reg3(self):
        binx = bytes_to_bins(self.reg3)
        str = ''
        i = 31
        for b1 in binx:
            str += b1
            if i == 31:
                str += " | EN_AUTOCALC_MB2 \n"
            if i == 30:
                str += " | EN_FIRST_WAVE \n"
            if i == 29:
                str += " | EN_ERR_VAL \n"
            if i == 27:
                str += " | SEL_TIMO_MB2 \n"
                
            if i == 8:
                str += " | DELVAL2 \n"            
            i -= 1
            
        str += " | ID3"
        return str

    def parse_reg4(self):
        binx = bytes_to_bins(self.reg4)
        str = ''
        i = 31
        for b1 in binx:
            str += b1
            if i == 27:
                str += " | k. d. \n"
            if i == 8:
                str += " | DELVAL3 \n"            
            i -= 1
            
        str += " | ID4"
        return str

    def parse_reg5(self):
        binx = bytes_to_bins(self.reg5)
        str = ''
        i = 31
        for b1 in binx:
            str += b1
            if i == 29:
                str += " | CONF_FIRE \n"
            if i == 28:
                str += " | EN_STARTNOISE \n"
            if i == 27:
                str += " | DIS_PHASESHIFT \n"
            if i == 24:
                str += " | REPEAT_FIRE \n"
            if i == 8:
                str += " | PHFIRE \n"            
            i -= 1
            
        str += " | ID5"
        return str
