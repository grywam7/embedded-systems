# HUB75 8 bit driver
#
# Andy Crook
#
# https://github.com/andycrook
# 
# 
#
# This driver is built for a 64x64 HUB75e LED matrix.
#
# Features:
#
#    Full R8G8B8 image support, 0-255 values
#    BMP (including 32 bit Alpha mode) loading, including chroma key 255,0,255 (magenta) for 1 bit transparency for small sprites
#    Saving to binary framebuffer for fast load - approx 10 ms
#    This allows full motion video, each frame is 16384 bytes, so limited to a few seconds unless read from SD (which can be slow)
#    BDF font loading (not recommended, they're just too large)
#    Custom font loading - mfont 'mini font' (and conversion to mfont)
#    3D OBJ model loading and rendering (limited speed with larger models)
#    Fully UV textured model support :)
#    Keyframe multi-animation-per-model animation support
#    Randomised animation system
#    Emission particle system
#
#
#
# May 2025

from rp2 import StateMachine, asm_pio, PIO
from micropython import const
import micropython
import _thread
import os
import rp2
import machine
from machine import I2C, Pin, SPI
import random
import sys
import math
import gc
from array import array

# Wiring on a pi pico:
#     /-----\
# R0  | o o | G0
# B0  | o o | GND
# R1  | o o | G1
# B1  \ o o | E
# A   / o o | B
# C   | o o | D
# CLK | o o | STB
# OEn | o o | GND
#     \-----/

# RGB pins start at GPIO2 ---> GPIO7 for R0 G0 B0 R1 G1 B1
# ROW select pins start at GPIO8 ---> GPIO12  for ABCDE
# CLK 13
# LAT 14
# OEn 15

# Warning - hub75 displays are sensitive to things that will cause ghosting.
# Ensure:
# The panel is provided 5v and enough current is available for it.
# The signals from your pico are level shifted from 3v3 to 5v.
# (you can get away with driving many panels from 3v3, but 5v is better)
# The connecting wires from pico to matrix are short - standard 20cm dupont jumpers on a breadboard
# may be too long. If you have ghosting pixels it may be these factors.

# LED Matrix Dimensions
MATRIX_SIZE_X = 64
MATRIX_SIZE_Y = 64

# --- Constants (global for the module) ---
PI = 3.1415927
TWO_PI = 6.2831853
HALF_PI = 1.5707963
INV_TWO_PI = 40.743665  # 256 / (2π) — fixed scale factor

# --- 256-entry sine lookup table (for 0 to 2π) ---
SIN_LUT = [math.sin(TWO_PI * i / 256) for i in range(256)]

DEBUG = False  # Set to True to enable debug prints

if DEBUG:

    def debug_print(*args, **kwargs):
        print(*args, **kwargs)

else:

    def debug_print(*args, **kwargs):
        pass


@micropython.native  # or @micropython.viper if rewritten with ptr access
def fast_sin(angle_rad):
    """Fast sine using fixed-point 256-entry LUT."""
    i = int(angle_rad * INV_TWO_PI) & 0xFF  # Wrap to 0–255
    return SIN_LUT[i]


@micropython.native
def fast_cos(angle_rad):
    """Fast cosine using offset sine LUT."""
    i = int(angle_rad * INV_TWO_PI) & 0xFF
    return SIN_LUT[(i + 64) & 0xFF]  # cos(x) = sin(x + π/2)


# PIO frequencies and overclocking
PIO_FREQ_LED = const(65_000_000)
PIO_FREQ_ROW = const(65_000_000)
PIO_FREQ_BRIGHT = const(30_000_000)  # lower = brighter
MACHINE_FREQ = const(250_000_000)  # reduce this if it seems unstable, at the cost of rendering speed

machine.freq(MACHINE_FREQ)

# Statemachines:

# There are 3:

# 1 led_data   - clocks out rgb data to a row and to row+32 in 0b00BGRBGR format
# 2 address_counter - selects the row for display - here ABCDE, then latches the latch on and off
# 3 output BCM- when a row is complete, this sm is triggered while the others stop to display the data


@asm_pio(
    out_init=(rp2.PIO.OUT_LOW,) * 6,
    sideset_init=(rp2.PIO.OUT_LOW,) * 1,
    set_init=(rp2.PIO.OUT_HIGH,) * 2,
    out_shiftdir=PIO.SHIFT_RIGHT,
)
def led_data():

    set(x, 31)
    in_(x, 5)
    in_(x, 1)
    wrap_target()
    set(x, 31)
    mov(x, isr)

    label("Byte Counter")
    pull().side(0)[1]
    nop()[1].side(0)
    out(pins, 6).side(1)
    nop()[1].side(1)
    jmp(x_dec, "Byte Counter")

    irq(block, 4)
    irq(block, 5)
    wrap()


@asm_pio(
    out_init=(rp2.PIO.OUT_LOW,) * 5,
    set_init=(rp2.PIO.OUT_HIGH,) * 1,
    out_shiftdir=PIO.SHIFT_RIGHT,
)
def address_counter():

    set(x, 31)  # number of rows - max 31 ABCDE
    label("Address Decrement")
    wait(1, irq, 4)
    mov(pins, x)
    set(pins, 1)
    set(pins, 0)
    irq(rel(0), 6)  # Trigger output SM to enable display
    wait(1, irq, 7)  # Wait for output SM to finish
    irq(clear, 5)
    jmp(x_dec, "Address Decrement")


@asm_pio(set_init=(rp2.PIO.OUT_HIGH,) * 1, out_shiftdir=rp2.PIO.SHIFT_LEFT)
def output():

    wrap_target()
    wait(1, irq, 6)  # Wait for address_counter to signal
    pull(noblock)  # Check for new delay value from Python
    mov(x, osr)  # Save OSR in X
    mov(y, x)
    set(pins, 0)  # Put display on

    label("y Decrement")
    nop()[5]
    jmp(y_dec, "y Decrement")

    set(pins, 1)  # Display back off
    irq(rel(0), 7)  # Signal address_counter we're done
    wrap()


# define the class


class Hub75:
    def __init__(
        self,
        data_pin_start=2,
        clock_pin=13,
        latch_pin_start=14,
        row_pin_start=8,
        num_rows=32,
        blocks_per_row=16,
    ):

        self.num_rows = num_rows
        self.blocks_per_row = blocks_per_row
        self.width = MATRIX_SIZE_X
        self.height = MATRIX_SIZE_Y

        self.led_data_sm = rp2.StateMachine(
            0,
            led_data,
            freq=PIO_FREQ_LED,
            out_base=Pin(data_pin_start),
            sideset_base=Pin(clock_pin),
        )
        self.address_counter_sm = rp2.StateMachine(
            1,
            address_counter,
            freq=PIO_FREQ_ROW,
            out_base=Pin(row_pin_start),
            set_base=Pin(latch_pin_start),
        )
        self.output_sm = rp2.StateMachine(
            2, output, freq=PIO_FREQ_BRIGHT, set_base=Pin(15)
        )

        # buffers are 2048 bytes * 6 frames for BCM. 2 pixels per byte for 64x64 pixels = 2048
        self.buffer_size = 2048


        # triple buffering
        self.frame_buffer = [bytearray(self.buffer_size) for _ in range(8)]
        self.frame_buffer_temp = [bytearray(self.buffer_size) for _ in range(8)]
        self.frame_buffer_ready = [
            bytearray(self.buffer_size) for _ in range(8)
        ]  # for triple buffering

        self.buffer_ready = False

        self.pixel_byte_index = array(
            "H", [0] * (self.width * self.height)
        )  # 13 bits is plenty for index
        self.pixel_shift = array("B", [0] * (self.width * self.height))  # 0 or 3
        self.pixel_mask = array(
            "B", [0] * (self.width * self.height)
        )  # 0b00000111 or 0b00111000

        # these are the boundaries for pixel drawing
        self.VIEWPORT_X = 0
        self.VIEWPORT_Y = 0
        self.VIEWPORT_XMAX = 64
        self.VIEWPORT_YMAX = 64

        # buffers for bits or for bmp data
        self.pixel_buffer = (
            []
        )  # this is 1 or 0, for text or graphic drawing (text only at the moment) - set the color when calling function
        self.text_start = (0, 0)
        self.pixel_buffer_BG = []
        self.scroll = 0
        self.scroll_max = 0
        self.marquee_new_text = ""

        self.font = []

        self.bmp_buffer = (
            []
        )  # this is for loading external small bmp images and reusing them. it's a list, each contatining a bitma

        self.gamma_lut = [0] * 256

        # generate the set_pixel tables needed for fast look up  of index etc
        self.generate_pixel_tables()
        self.update_rgb_lut()  # needs to be called on bitplane change

        # start PIO statemachines
        self.address_counter_sm.active(1)
        self.led_data_sm.active(1)
        self.output_sm.active(1)

        # start rendering thread
        self.frame_buffer_lock = _thread.allocate_lock()
        self.running = True
        _thread.start_new_thread(self.send_frames, ())

    @micropython.native
    def send_frames(self):
        sm_out = self.output_sm.put
        sm_led = self.led_data_sm.put

        # Dynamic bitplane schedule generator

        def generate_schedule(bitplanes):
            # Binary-weighted repeating schedule to approximate PWM brightness
            schedule = []
            for i in range(bitplanes):
                weight = 1 << i
                # Normalize: reduce repeats for higher bitplanes to limit frame time
                if bitplanes == 5:
                    repeats = 1 if i < 5 else 2
                elif bitplanes == 6:
                    repeats = 1 if i < 5 else 2
                elif bitplanes == 8:
                    repeats = 1 if i < 6 else 2 if i < 7 else 4
                else:
                    repeats = 1
                schedule.append((repeats, i))
            return schedule

        bitplane_schedule = generate_schedule(8)

        while self.running:
            if self.buffer_ready:
                self.frame_buffer, self.frame_buffer_ready = (
                    self.frame_buffer_ready,
                    self.frame_buffer,
                )
                self.buffer_ready = False

            fb = self.frame_buffer

            for repeats, index in bitplane_schedule:
                delay_val = 31 if index >= 5 else (1 << index) - 1
                for _ in range(repeats):
                    sm_out(delay_val)
                    sm_led(fb[index])

    @micropython.native
    def gamma_correct(self, val):
        return self.gamma_lut[val]

    @micropython.native
    def update_rgb_lut(self):
        bitplanes = 8
        max_val = (1 << bitplanes) - 1
        self.rgb_lut = bytearray(256)
        for i in range(256):
            self.rgb_lut[i] = (i * max_val + 127) // 255

    @micropython.native
    def generate_pixel_tables(self):
        # generates look up tables for set_pixel
        self.pixel_byte_index_buf = bytearray(self.width * self.height * 2)  # uint16
        self.pixel_shift_buf = bytearray(self.width * self.height)  # uint8
        self.pixel_mask_buf = bytearray(self.width * self.height)  # uint8

        p_index = memoryview(self.pixel_byte_index_buf)
        p_shift = memoryview(self.pixel_shift_buf)
        p_mask = memoryview(self.pixel_mask_buf)

        for y in range(64):
            y_mapped = 31 - (y & 31)
            offset = (y >> 5) & 1
            shift = 3 * offset
            mask = 0b00000111 << shift

            for x in range(64):
                idx = y * 64 + x
                byte_index = x + y_mapped * 64

                p_index[idx * 2] = byte_index & 0xFF  # LSB
                p_index[idx * 2 + 1] = (byte_index >> 8) & 0xFF  # MSB
                p_shift[idx] = shift
                p_mask[idx] = mask

        gamma = 2.2

        for g in range(256):
            self.gamma_lut[g] = self.adjust_gamma(g, gamma)

    @micropython.viper
    def set_pixel(
        self, x: int, y: int, g: int, r: int, b: int, vx: int, vy: int, vw: int, vh: int
    ):
        if x < vx or x >= vw or y < vy or y >= vh:
            return

        index: int = y * 64 + x

        byte_index = ptr16(self.pixel_byte_index_buf)[index]
        shift = ptr8(self.pixel_shift_buf)[index]
        mask = ptr8(self.pixel_mask_buf)[index]

        for bitplane in range(8):
            fb_ptr = ptr8(self.frame_buffer_temp[bitplane])
            bit = 1 << bitplane

            # Calculate the RGB bits for this bitplane
            bits = (
                ((r & bit) >> bitplane) << 2
                | ((g & bit) >> bitplane) << 1
                | ((b & bit) >> bitplane)
            )
            val = (bits << shift) & 0xFF

            # Apply pixel data with bit mask
            fb_ptr[byte_index] = (fb_ptr[byte_index] & (~mask)) | val

    @micropython.native
    def get_pixel(self, x, y):  # returns a tuple of r,g,b
        rgb = self.get_pixelv(x, y)
        g = (rgb >> 16) & 0xFF
        r = (rgb >> 8) & 0xFF
        b = rgb & 0xFF
        return (r, g, b)

    @micropython.viper
    def get_pixelv(self, x: int, y: int) -> int:
        if x < 0 or x >= 64 or y < 0 or y >= 64:
            return 0

        index: int = y * 64 + x

        byte_index = ptr16(self.pixel_byte_index_buf)[index]
        shift = ptr8(self.pixel_shift_buf)[index]
        mask = ptr8(self.pixel_mask_buf)[index]

        r: int = 0
        g: int = 0
        b: int = 0

        for bitplane in range(8):
            fb_ptr = ptr8(self.frame_buffer_temp[bitplane])
            val = (fb_ptr[byte_index] & mask) >> shift

            # Extract RGB bits (same encoding as set_pixel)
            r_bit = (val >> 2) & 1
            g_bit = (val >> 1) & 1
            b_bit = (val >> 0) & 1

            r |= r_bit << bitplane
            g |= g_bit << bitplane
            b |= b_bit << bitplane

        # Return packed RGB: 0xRRGGBB
        return (r << 16) | (g << 8) | b

    # drawing functions

    @micropython.native
    def hline(self, x, y, length, g, r, b, vx=0, vy=0, vxmax=64, vymax=64):
        self.hlinev(x, y, length, g, r, b, vx, vy, vxmax, vymax)

    @micropython.viper
    def hlinev(
        self,
        x: int,
        y: int,
        length: int,
        g: int,
        r: int,
        b: int,
        vx: int,
        vy: int,
        vxmax: int,
        vymax: int,
    ):
        for i in range(length):
            self.set_pixel(x + i, y, g, r, b, vx, vy, vxmax, vymax)

    @micropython.native
    def vline(self, x, y, length, g, r, b, vx=0, vy=0, vxmax=64, vymax=64):
        self.vlinev(x, y, length, g, r, b, vx, vy, vxmax, vymax)

    @micropython.viper
    def vlinev(
        self,
        x: int,
        y: int,
        length: int,
        g: int,
        r: int,
        b: int,
        vx: int,
        vy: int,
        vxmax: int,
        vymax: int,
    ):
        for i in range(length):
            self.set_pixel(x, y + i, g, r, b, vx, vy, vxmax, vymax)

    @micropython.native
    def line(self, x, y, x1, y1, g, r, b, vx=0, vy=0, vxmax=64, vymax=64):
        self.linev(x, y, x1, y1, g, r, b, vx, vy, vxmax, vymax)

    @micropython.viper
    def linev(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        g: int,
        r: int,
        b: int,
        vx: int,
        vy: int,
        vxmax: int,
        vymax: int,
    ):
        dx: int = x1 - x0
        dx = dx if dx >= 0 else -dx
        dy: int = y1 - y0
        dy = -(dy if dy >= 0 else -dy)

        sx: int = 1 if x0 < x1 else -1
        sy: int = 1 if y0 < y1 else -1
        err: int = dx + dy
        e2: int

        while True:
            self.set_pixel(x0, y0, g, r, b, vx, vy, vxmax, vymax)
            if x0 == x1 and y0 == y1:
                break
            e2 = err << 1
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    @micropython.native
    def box(self, x, y, width, height, g, r, b, filled, vx=0, vy=0, vxmax=64, vymax=64):
        self.boxv(x, y, width, height, g, r, b, filled, vx, vy, vxmax, vymax)

    @micropython.viper
    def boxv(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        g: int,
        r: int,
        b: int,
        filled: int,
        vx: int,
        vy: int,
        vxmax: int,
        vymax: int,
    ):
        if filled:
            for xx in range(width):
                for yy in range(height):
                    self.set_pixel(x + xx, y + yy, g, r, b, vx, vy, vxmax, vymax)
        else:
            self.hline(x, y, width, g, r, b, vx, vy, vxmax, vymax)  # Top
            self.hline(
                x, y + height - 1, width, g, r, b, vx, vy, vxmax, vymax
            )  # Bottom
            self.vline(x, y, height, g, r, b, vx, vy, vxmax, vymax)  # Left
            self.vline(x + width - 1, y, height, g, r, b, vx, vy, vxmax, vymax)  # Right

    @micropython.native
    def ellipse(x0, y0, rx, ry, g, r, b, filled, vx=0, vy=0, vxmax=64, vymax=64):
        self.ellipsev(x0, y0, rx, ry, g, r, b, filled, vx, vy, vxmax, vymax)

    @micropython.viper
    def ellipsev(
        self,
        x0: int,
        y0: int,
        rx: int,
        ry: int,
        g: int,
        r: int,
        b: int,
        filled: int,
        vx: int,
        vy: int,
        vxmax: int,
        vymax: int,
    ):
        rx2: int = rx * rx
        ry2: int = ry * ry
        x: int = 0
        y: int = ry
        dx: int = 0
        dy: int = 2 * rx2 * y

        p: int = ry2 - rx2 * ry + (rx2 >> 2)
        while dx < dy:
            self._draw_hspan(x0, y0 + y, x, g, r, b, filled, vx, vy, vxmax, vymax)
            self._draw_hspan(x0, y0 - y, x, g, r, b, filled, vx, vy, vxmax, vymax)
            x += 1
            dx += 2 * ry2
            if p < 0:
                p += ry2 + dx
            else:
                y -= 1
                dy -= 2 * rx2
                p += ry2 + dx - dy

        xp: int = x
        yp: int = y
        t1: int = xp * 2 + 1
        t1 = (t1 * t1) >> 2  # (2x+1)^2 / 4
        t2: int = yp - 1
        t2 = t2 * t2
        p = ry2 * t1 + rx2 * t2 - rx2 * ry2

        while y >= 0:
            self._draw_hspan(x0, y0 + y, x, g, r, b, filled, vx, vy, vxmax, vymax)
            self._draw_hspan(x0, y0 - y, x, g, r, b, filled, vx, vy, vxmax, vymax)
            y -= 1
            dy -= 2 * rx2
            if p > 0:
                p += rx2 - dy
            else:
                x += 1
                dx += 2 * ry2
                p += rx2 - dy + dx

    @micropython.native
    def _draw_hspan(self, cx, cy, x, g, r, b, filled, vx, vy, vxmax, vymax):
        if filled:
            self.hline(cx - x, cy, (x << 1) + 1, g, r, b)
        else:
            self.set_pixel(cx - x, cy, g, r, b, vx, vy, vxmax, vymax)
            if x != 0:
                self.set_pixel(cx + x, cy, g, r, b, vx, vy, vxmax, vymax)

    @micropython.native
    def polygon(self, points, g, r, b, closed=True):
        if len(points) < 2:
            return  # Need at least 2 points
        for i in range(len(points) - 1):
            x0, y0 = points[i]
            x1, y1 = points[i + 1]
            self.line(x0, y0, x1, y1, g, r, b)
        if closed:
            x0, y0 = points[-1]
            x1, y1 = points[0]
            self.line(x0, y0, x1, y1, g, r, b)

    @micropython.native
    def refresh(self):
        # swap buffers
        with self.frame_buffer_lock:
            self.frame_buffer_temp, self.frame_buffer_ready = (
                self.frame_buffer_ready,
                self.frame_buffer_temp,
            )
            self.buffer_ready = True

    @micropython.viper
    def fill(self, g: int = 0, b: int = 0, r: int = 0):
        num_planes: int = int(8)
        i: int
        bitplane: int
        fill: int
        buf: ptr8
        bytecount: int = 2048  # Or len(self.frame_buffer_temp[0]) if dynamic

        for bitplane in range(num_planes):
            fill = (
                (((b >> bitplane) & 1) << 2)
                | (((g >> bitplane) & 1) << 1)
                | ((r >> bitplane) & 1)
            )
            fill = (fill << 3) | fill  # replicate 3-bit value across byte

            buf = ptr8(self.frame_buffer_temp[bitplane])
            for i in range(bytecount):
                buf[i] = fill

    @micropython.viper
    def clear(self):
        num_planes = int(8)
        for bitplane in range(num_planes):
            buf = ptr16(self.frame_buffer_temp[bitplane])
            buf2 = ptr16(self.frame_buffer_ready[bitplane])
            for i in range(1024):  # 2 bytes at a time (2048 bytes total)
                buf[i] = 0
                buf2[i] = 0

    @micropython.native
    def load_bmp(
        self,
        filename,
        x1=0,
        y1=0,
        gamma=2.2,
        brightness=1.0,
        contrast=1.0,
        buffered=0,
        scale=1,
        hue=0,
        return_data=0,
        blendmode="none",
    ):

        if blendmode == "alpha":
            mode = 1
        if blendmode == "multiply":
            mode = 2
        if blendmode == "screen":
            mode = 3
        if blendmode == "lighten":
            mode = 4
        if blendmode == "darken":
            mode = 5
        if blendmode == "add":
            mode = 6

        scale_down = 1 / scale

        if buffered == 1:
            bmp_load = []

        with open(filename, "rb") as f:
            f.seek(18)
            width = int.from_bytes(f.read(4), "little")
            f.seek(22)
            height = int.from_bytes(f.read(4), "little")
            f.seek(28)
            bpp = int.from_bytes(f.read(2), "little")  # Bits per pixel

            if bpp not in (24, 32):
                raise ValueError("Only 24-bit and 32-bit BMPs supported")
            if return_data == 1:
                if bpp == 24:
                    texture = bytearray(width * height * 3)
                if bpp == 32:
                    texture = bytearray(width * height * 4)

            f.seek(30)
            compression = int.from_bytes(f.read(4), "little")
            if compression != 0:
                raise ValueError("Compressed BMPs not supported")

            f.seek(54)

            bytes_per_pixel = bpp // 8
            row_bytes = (width * bytes_per_pixel + 3) & ~3
            buffer = bytearray(row_bytes)

            hue_shift_value = hue

            for y in range(height - 1, -1, -1):  # BMP is bottom-up
                f.readinto(buffer)

                for x in range(width):
                    base = x * bytes_per_pixel
                    b_raw = buffer[base]
                    g_raw = buffer[base + 1]
                    r_raw = buffer[base + 2]
                    if bpp == 32:
                        a_raw = buffer[base + 3]
                    else:
                        a_raw = 0
                    # Ignore alpha byte (base + 3) if bpp == 32

                    r = self.adjust_gamma(r_raw, gamma)
                    g = self.adjust_gamma(g_raw, gamma)
                    b = self.adjust_gamma(b_raw, gamma)

                    r = self.adjust_brightness(r, brightness)
                    g = self.adjust_brightness(g, brightness)
                    b = self.adjust_brightness(b, brightness)

                    r = self.adjust_contrast(r, contrast)
                    g = self.adjust_contrast(g, contrast)
                    b = self.adjust_contrast(b, contrast)

                    # Clamp to [0, 255]
                    r = min(max(r, 0), 255)
                    g = min(max(g, 0), 255)
                    b = min(max(b, 0), 255)

                    if return_data == 1:
                        
                        yy = y
                        
                        idx = (yy * width + x) * 3

                        r, g, b = self.hue_shift_rgb888(r, g, b, hue_shift_value)

                        texture[idx] = r
                        texture[idx + 1] = g
                        texture[idx + 2] = b

                    if (r_raw, g_raw, b_raw) != (255, 0, 255):  # Transparent check
                        if buffered == 1:
                            bmp_load.append([x, y, r, g, b])
                        else:
                            r, g, b = self.hue_shift_rgb888(r, g, b, hue_shift_value)
                            pass
                            if scale_down > 1:
                                x_BMP = int(x / scale_down) + x1
                                y_BMP = int(y / scale_down) + y1
                            else:
                                x_BMP = x + x1
                                y_BMP = y + y1

                            if blendmode == "none":
                                self.set_pixel(
                                    x_BMP,
                                    y_BMP,
                                    g,
                                    b,
                                    r,
                                    self.VIEWPORT_X,
                                    self.VIEWPORT_Y,
                                    self.VIEWPORT_XMAX,
                                    self.VIEWPORT_YMAX,
                                )
                            else:

                                get_col = self.get_pixel(x_BMP, y_BMP)
                                rr, gg, bb = self.blend_rgb888_pixel(
                                    get_col[0],
                                    get_col[1],
                                    get_col[2],
                                    r,
                                    g,
                                    b,
                                    a_raw,
                                    mode,
                                )

                                self.set_pixel(
                                    x_BMP,
                                    y_BMP,
                                    gg,
                                    bb,
                                    rr,
                                    self.VIEWPORT_X,
                                    self.VIEWPORT_Y,
                                    self.VIEWPORT_XMAX,
                                    self.VIEWPORT_YMAX,
                                )

        if buffered == 1:
            self.bmp_buffer.append(bmp_load)
        if return_data == 1:
            print("returning bmp")
            return width, height, texture

    # colour adjustments

    @micropython.native
    def adjust_gamma(self, value, gamma):
        new_value = (value / 255) ** gamma * 255
        return max(0, min(255, int(round(new_value))))

    @micropython.native
    def adjust_brightness(self, value, brightness):
        new_value = value * brightness
        return max(0, min(255, int(round(new_value))))

    @micropython.native
    def adjust_contrast(self, value, contrast):
        new_value = (value - 128) * contrast + 128
        return max(0, min(255, int(round(new_value))))

    @micropython.native
    def blend_rgb888_pixel(self, R0, G0, B0, R1, G1, B1, A1, mode="none"):
        """
        Blend two RGB888 pixels using the given blending mode and alpha.

        Returns:
            (R_final, G_final, B_final): Tuple[int, int, int] – Resulting 8-bit color
        """

        # Normalize RGB
        r0, g0, b0 = R0 / 255.0, G0 / 255.0, B0 / 255.0
        r1, g1, b1 = R1 / 255.0, G1 / 255.0, B1 / 255.0

        a1 = A1 / 255.0

        # Blend modes

        if mode == 1:
            rf, gf, bf = (
                (r1 * a1) + (r0 * (1 - a1)),
                (g1 * a1) + (g0 * (1 - a1)),
                (b1 * a1) + (b0 * (1 - a1)),
            )
        elif mode == 2:
            rm, gm, bm = r0 * r1, g0 * g1, b0 * b1
        elif mode == 3:
            rm, gm, bm = (
                1 - (1 - r0) * (1 - r1),
                1 - (1 - g0) * (1 - g1),
                1 - (1 - b0) * (1 - b1),
            )
        elif mode == 4:
            rm, gm, bm = max(r0, r1), max(g0, g1), max(b0, b1)
        elif mode == 5:
            rm, gm, bm = min(r0, r1), min(g0, g1), min(b0, b1)
        elif mode == 6:
            rm, gm, bm = min(r0 + r1, 1), min(g0 + g1, 1), min(b0 + b1, 1)
        elif mode == 7:
            rm, gm, bm = max(r0 - r1, 0), max(g0 - g1, 0), max(b0 - b1, 0)

        else:
            raise ValueError("Unsupported blend mode: What more do you want??")

        if mode != 1:
            # Alpha blend with base
            rf = (1 - a1) * r0 + a1 * rm
            gf = (1 - a1) * g0 + a1 * gm
            bf = (1 - a1) * b0 + a1 * bm

        # Return 8-bit RGB
        R_final = min(255, max(0, int(rf * 255 + 0.5)))
        G_final = min(255, max(0, int(gf * 255 + 0.5)))
        B_final = min(255, max(0, int(bf * 255 + 0.5)))

        return R_final, G_final, B_final

    @micropython.viper
    def blend_rgb888_pixelv(
        self, R0: int, G0: int, B0: int, R1: int, G1: int, B1: int, A1: int, mode: int
    ) -> int:
        # Scale color channels from 0–255 to 0–65535 (16.8 fixed-point)
        r0 = R0 * 256
        g0 = G0 * 256
        b0 = B0 * 256
        r1 = R1 * 256
        g1 = G1 * 256
        b1 = B1 * 256
        a1 = A1 * 257

        inv_a1 = 65536 - a1

        # Init output channels
        rf = gf = bf = 0
        rm = gm = bm = 0

        # Modes:
        if mode == 1:  # alpha only
            rf = (r1 * a1 + r0 * inv_a1) >> 16
            gf = (g1 * a1 + g0 * inv_a1) >> 16
            bf = (b1 * a1 + b0 * inv_a1) >> 16

        elif mode == 2:  # multiply
            rm = (r0 * r1) >> 16
            gm = (g0 * g1) >> 16
            bm = (b0 * b1) >> 16

        elif mode == 3:  # screen
            rm = 65536 - (((65536 - r0) * (65536 - r1)) >> 16)
            gm = 65536 - (((65536 - g0) * (65536 - g1)) >> 16)
            bm = 65536 - (((65536 - b0) * (65536 - b1)) >> 16)

        elif mode == 4:  # lighten
            rm = r0 if r0 > r1 else r1
            gm = g0 if g0 > g1 else g1
            bm = b0 if b0 > b1 else b1

        elif mode == 5:  # darken
            rm = r0 if r0 < r1 else r1
            gm = g0 if g0 < g1 else g1
            bm = b0 if b0 < b1 else b1

        elif mode == 6:  # add
            rm = r0 + r1
            gm = g0 + g1
            bm = b0 + b1
            if rm > 65535:
                rm = 65535
            if gm > 65535:
                gm = 65535
            if bm > 65535:
                bm = 65535

        elif mode == 7:  # subtract
            rm = r0 - r1 if r0 > r1 else 0
            gm = g0 - g1 if g0 > g1 else 0
            bm = b0 - b1 if b0 > b1 else 0

        else:
            return 0  # unsupported mode

        # Apply alpha if not already done (mode 1 is pre-blended)
        if mode != 1:
            rf = (inv_a1 * r0 + a1 * rm) >> 16
            gf = (inv_a1 * g0 + a1 * gm) >> 16
            bf = (inv_a1 * b0 + a1 * bm) >> 16

        # Convert back to 8-bit RGB
        Rf = rf >> 8
        Gf = gf >> 8
        Bf = bf >> 8

        if Rf > 255:
            Rf = 255
        if Gf > 255:
            Gf = 255
        if Bf > 255:
            Bf = 255

        # Return packed RGB888
        return (Rf << 16) | (Gf << 8) | Bf

    @micropython.native
    def rgb_to_hsv(self, r, g, b):
        # r, g, b are in [0.0, 1.0]
        maxc = max(r, g, b)
        minc = min(r, g, b)
        v = maxc
        if minc == maxc:
            return 0.0, 0.0, v
        s = (maxc - minc) / maxc
        rc = (maxc - r) / (maxc - minc)
        gc = (maxc - g) / (maxc - minc)
        bc = (maxc - b) / (maxc - minc)
        if r == maxc:
            h = bc - gc
        elif g == maxc:
            h = 2.0 + rc - bc
        else:
            h = 4.0 + gc - rc
        h = (h / 6.0) % 1.0
        return h, s, v

    @micropython.native
    def hsv_to_rgb(self, h, s, v):
        if s == 0.0:
            return v, v, v
        i = int(h * 6.0)
        f = (h * 6.0) - i
        p = v * (1.0 - s)
        q = v * (1.0 - s * f)
        t = v * (1.0 - s * (1.0 - f))
        i = i % 6
        if i == 0:
            return v, t, p
        if i == 1:
            return q, v, p
        if i == 2:
            return p, v, t
        if i == 3:
            return p, q, v
        if i == 4:
            return t, p, v
        return v, p, q

    @micropython.native
    def hue_shift_rgb888(self, R: int, G: int, B: int, degrees: float):
     
        # Normalize RGB
        r = R / 255.0
        g = G / 255.0
        b = B / 255.0

        # Convert to HSV
        h, s, v = self.rgb_to_hsv(r, g, b)

        # Optional tweak: reduce saturation to avoid color artifacts
        if s > 0.95:
            s *= 0.95

        # Shift hue
        h = (h + degrees / 360.0) % 1.0

        # Convert back to RGB
        r, g, b = self.hsv_to_rgb(h, s, v)

        # Scale to 8-bit
        R_out = min(255, max(0, int(r * 255 + 0.5)))
        G_out = min(255, max(0, int(g * 255 + 0.5)))
        B_out = min(255, max(0, int(b * 255 + 0.5)))

        return R_out, G_out, B_out

    @micropython.viper
    def show_bmp(self, bitmap: int, x: int, y: int):
        bmp = self.bmp_buffer[bitmap]
        vp_x: int = int(self.VIEWPORT_X)
        vp_y: int = int(self.VIEWPORT_Y)
        vp_xmax: int = int(self.VIEWPORT_XMAX)
        vp_ymax: int = int(self.VIEWPORT_YMAX)
        set_px = self.set_pixel

        n: int = int(len(bmp))
        i: int = 0
        while i < n:
            p = bmp[i]
            xx: int = int(p[0]) + x
            yy: int = int(p[1]) + y
            r: int = int(p[2])
            g: int = int(p[3])
            b: int = int(p[4])
            set_px(xx, yy, r, g, b, vp_x, vp_y, vp_xmax, vp_ymax)
            i += 1

    @micropython.native
    def save_frame(self, filename, chunk_size=2048):
        # save the frame buffer as a file - once all drawing operations have been done, its
        # more efficient and fast to load the .bin file for the whole screen as a base to
        # then draw dynamic elements on
        with open(filename, "wb") as f:
            # output all bitplane buffers as a contiguous file - 2048 bytes per frame
            for fr in range(8):
                f.write(self.frame_buffer_temp[fr])

    @micropython.native
    def blend_frames(self, path1, path2, value=128, mode="fade"):

        with open(path1, "rb") as f1, open(path2, "rb") as f2:
            for i in range(2048):  # pixel byte index
                r1 = g1 = b1 = 0
                r2 = g2 = b2 = 0
                rr1 = gg1 = bb1 = 0
                rr2 = gg2 = bb2 = 0

                for bit in range(8):
                    # Each bitplane starts at offset = bit * 2048
                    f1.seek(bit * 2048 + i)
                    f2.seek(bit * 2048 + i)
                    v1 = ord(f1.read(1))
                    v2 = ord(f2.read(1))

                    mask = 1 << bit

                    if v1 & 0x01:
                        r1 |= mask
                    if v1 & 0x02:
                        g1 |= mask
                    if v1 & 0x04:
                        b1 |= mask

                    if v2 & 0x01:
                        r2 |= mask
                    if v2 & 0x02:
                        g2 |= mask
                    if v2 & 0x04:
                        b2 |= mask

                    # Bottom pixel (bits 3–5)
                    if v1 & 0x20:
                        rr1 |= mask
                    if v1 & 0x10:
                        gg1 |= mask
                    if v1 & 0x08:
                        bb1 |= mask

                    if v2 & 0x20:
                        rr2 |= mask
                    if v2 & 0x10:
                        gg2 |= mask
                    if v2 & 0x08:
                        bb2 |= mask

                if mode == "fade":
                    alpha = value
                    # Blend RGB
                    r = (r1 * (255 - alpha) + r2 * alpha) >> 8
                    g = (g1 * (255 - alpha) + g2 * alpha) >> 8
                    b = (b1 * (255 - alpha) + b2 * alpha) >> 8

                    # Blend bottom pixel
                    rr = (rr1 * (255 - alpha) + rr2 * alpha) >> 8
                    gg = (gg1 * (255 - alpha) + gg2 * alpha) >> 8
                    bb = (bb1 * (255 - alpha) + bb2 * alpha) >> 8

                if mode == "add":
                    add = value
                    r = min(r1 + ((r2 * add) >> 8), 255)
                    g = min(g1 + ((g2 * add) >> 8), 255)
                    b = min(b1 + ((b2 * add) >> 8), 255)

                    rr = min(rr1 + ((rr2 * add) >> 8), 255)
                    gg = min(gg1 + ((gg2 * add) >> 8), 255)
                    bb = min(bb1 + ((bb2 * add) >> 8), 255)

                if mode == "multiply":
                    r = (r1 * r2) >> 8
                    g = (g1 * g2) >> 8
                    b = (b1 * b2) >> 8

                    rr = (rr1 * rr2) >> 8
                    gg = (gg1 * gg2) >> 8
                    bb = (bb1 * bb2) >> 8

                if mode == "screen":
                    r = 255 - (((255 - r1) * (255 - r2)) >> 8)
                    g = 255 - (((255 - g1) * (255 - g2)) >> 8)
                    b = 255 - (((255 - b1) * (255 - b2)) >> 8)

                    rr = 255 - (((255 - rr1) * (255 - rr2)) >> 8)
                    gg = 255 - (((255 - gg1) * (255 - gg2)) >> 8)
                    bb = 255 - (((255 - bb1) * (255 - bb2)) >> 8)

                if mode == "lighten":
                    r = max(r1, r2)
                    g = max(g1, g2)
                    b = max(b1, b2)

                    rr = max(rr1, rr2)
                    gg = max(gg1, gg2)
                    bb = max(bb1, bb2)

                if mode == "darken":
                    r = min(r1, r2)
                    g = min(g1, g2)
                    b = min(b1, b2)

                    rr = min(rr1, rr2)
                    gg = min(gg1, gg2)
                    bb = min(bb1, bb2)
                if mode == "overlay":

                    def blend_overlay(a, b):
                        return (
                            (a * b) >> 7
                            if a < 128
                            else 255 - (((255 - a) * (255 - b)) >> 7)
                        )

                    r = blend_overlay(r1, r2)
                    g = blend_overlay(g1, g2)
                    b = blend_overlay(b1, b2)

                    rr = blend_overlay(rr1, rr2)
                    gg = blend_overlay(gg1, gg2)
                    bb = blend_overlay(bb1, bb2)

                # Re-pack into 8 bitplanes
                for bit in range(8):
                    val = 0
                    if r & (1 << bit):
                        val |= 0x01
                    if g & (1 << bit):
                        val |= 0x02
                    if b & (1 << bit):
                        val |= 0x04

                    if rr & (1 << bit):
                        val |= 0x20  # bottom R (bit 5)
                    if gg & (1 << bit):
                        val |= 0x10  # bottom G (bit 4)
                    if bb & (1 << bit):
                        val |= 0x08  # bottom B (bit 3)

                    self.frame_buffer_temp[bit][i] = val

    @micropython.native
    def load_frame(self, filename, chunk_size=2048):
        # very fast loading of a screen
        with open(filename, "rb") as f:

            for i in range(8):
                bytes_read = f.readinto(self.frame_buffer_temp[i])

    def load_framebuffer(self, data):
        for i in range(8):
            self.frame_buffer_temp[i][:] = data[i*2048:(i+1)*2048]
        # then call self.refresh() to publish (main.py already does)

    @micropython.native
    def scroll_vertical(self, amount):
        amount = amount % 64  # wrap around
        if amount == 0:
            return

        for bitplane in range(8):
            src = self.frame_buffer_temp[bitplane]
            temp = bytearray(self.buffer_size)

            for y in range(64):
                src_y = (y + amount) % 64
                for x in range(64):
                    src_index = (src_y % 32) * 64 + x
                    dst_index = (y % 32) * 64 + x

                    src_byte = src[src_index]
                    if src_y < 32:
                        src_pixel = src_byte & 0b00000111
                    else:
                        src_pixel = (src_byte >> 3) & 0b00000111

                    dst_byte = temp[dst_index]
                    if y < 32:
                        dst_byte = (dst_byte & 0b11111000) | src_pixel
                    else:
                        dst_byte = (dst_byte & 0b11000111) | (src_pixel << 3)

                    temp[dst_index] = dst_byte

            self.frame_buffer_temp[bitplane][:] = temp

    @micropython.native
    def scroll_horizontal(self, amount):
        amount = amount % 64  # wrap around
        if amount == 0:
            return

        for bitplane in range(8):
            src = self.frame_buffer_temp[bitplane]
            temp = bytearray(self.buffer_size)

            for y in range(64):
                for x in range(64):
                    src_x = (x + amount) % 64
                    src_index = (y % 32) * 64 + src_x
                    dst_index = (y % 32) * 64 + x

                    src_byte = src[src_index]
                    if y < 32:
                        src_pixel = src_byte & 0b00000111
                    else:
                        src_pixel = (src_byte >> 3) & 0b00000111

                    dst_byte = temp[dst_index]
                    if y < 32:
                        dst_byte = (dst_byte & 0b11111000) | src_pixel
                    else:
                        dst_byte = (dst_byte & 0b11000111) | (src_pixel << 3)

                    temp[dst_index] = dst_byte

            self.frame_buffer_temp[bitplane][:] = temp

    @micropython.native
    def count_bmp(self):
        # how many bmps ate stored internally
        return len(self.bmp_buffer), [len(b) for b in self.bmp_buffer]

    @micropython.native
    def erase_bmp(self, bitmap):
        # remove a bmo from internal storage
        del self.bmp_buffer[bitmap]
        gc.collect()

    @micropython.native
    def get_adjacent_pixels(self, pixels, surround):
        # for all pixels in pixels (set of x,y coords), work out the boundary pixels and returns as a set
        # surround = 0 ignores corners, 1 is more blocky and complete
        # This is used in text drawing to draw borders around glyphs
        adjacent = set()
        if surround == 0:
            for x, y, p in pixels:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    neighbor_test = (x + dx, y + dy, 1)
                    neighbor = (x + dx, y + dy, 0)
                    if neighbor_test not in pixels:
                        adjacent.add(neighbor)

        else:

            for x, y, p in pixels:
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx == 0 and dy == 0:
                            continue  # skip the original pixel
                        neighbor_test = (x + dx, y + dy, 1)
                        neighbor = (x + dx, y + dy, 0)
                        if neighbor_test not in pixels:
                            adjacent.add(neighbor)

        return adjacent

    @micropython.native
    def load_bdf_font(self, path, code_range=(32, 127)):
        font = {"ascent": 0, "descent": 0, "default_char": 32, "glyphs": {}}

        try:
            f = open(path, "r", encoding="latin-1")
        except Exception as e:
            raise RuntimeError("Failed to open BDF: %s" % e)

        in_char = False
        bitmap = []
        current = {}

        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if not parts:
                continue

            cmd = parts[0]

            # Global font info
            if cmd == "FONT_ASCENT" and len(parts) > 1:
                try:
                    font["ascent"] = int(parts[1])
                except:
                    pass
            elif cmd == "FONT_DESCENT" and len(parts) > 1:
                try:
                    font["descent"] = int(parts[1])
                except:
                    pass
            elif cmd == "DEFAULT_CHAR" and len(parts) > 1:
                try:
                    font["default_char"] = int(parts[1])
                except:
                    pass

            # Glyph block
            elif cmd == "STARTCHAR":
                in_char = True
                current = {
                    "name": parts[1] if len(parts) > 1 else "",
                    "encoding": -1,
                    "width": 0,
                    "height": 0,
                    "xoff": 0,
                    "yoff": 0,
                    "x_advance": 0,
                    "data": [],
                }
                bitmap = []

            elif cmd == "ENCODING" and in_char and len(parts) > 1:
                try:
                    current["encoding"] = int(parts[1])
                except:
                    current["encoding"] = -1

            elif cmd == "DWIDTH" and in_char and len(parts) >= 1:
                try:
                    current["x_advance"] = int(parts[1])
                except:
                    pass

            elif cmd == "BBX" and in_char and len(parts) >= 5:
                try:
                    current["width"] = int(parts[1])
                    current["height"] = int(parts[2])
                    current["xoff"] = int(parts[3])
                    current["yoff"] = int(parts[4])

                except:
                    pass

            elif cmd == "BITMAP" and in_char:

                bitmap = []

            elif cmd == "ENDCHAR" and in_char:
                code = current["encoding"]
                if code_range[0] <= code <= code_range[1]:
                    current["data"] = bitmap
                    font["glyphs"][code] = current
                in_char = False
                current = {}
                bitmap = []

            elif in_char and cmd not in (
                "STARTCHAR",
                "ENCODING",
                "SWIDTH",
                "DWIDTH",
                "BBX",
                "BITMAP",
                "ENDCHAR",
            ):
                try:
                    val = int(line, 16)
                    row_bytes = (current["width"] + 7) // 8
                    for i in range(row_bytes):
                        byte = (val >> (8 * (row_bytes - 1 - i))) & 0xFF
                        bitmap.append(byte)
                except:
                    print("Invalid hex line:", line)

        f.close()
        return font

    @micropython.native
    def save_minifont(self, path):
        with open(path, "wb") as f:
            f.write(bytes([self.font["ascent"], self.font["descent"]]))
            f.write(len(self.font["glyphs"]).to_bytes(2, "big"))

            for codepoint, glyph in self.font["glyphs"].items():
                row_bytes = (glyph["width"] + 7) // 8
                data = glyph["data"]
                f.write(codepoint.to_bytes(2, "big"))
                f.write(
                    bytes(
                        [
                            glyph["width"],
                            glyph["height"],
                            glyph["xoff"] & 0xFF,
                            glyph["yoff"] & 0xFF,
                            glyph["x_advance"] & 0xFF,
                            len(data),
                        ]
                    )
                )
                f.write(bytes(data))

    @micropython.native
    def load_minifont(self, path):
        self.pixel_buffer = []
        self.font = []
        with open(path, "rb") as f:
            ascent = int.from_bytes(f.read(1), "big")
            descent = int.from_bytes(f.read(1), "big")
            num_glyphs = int.from_bytes(f.read(2), "big")

            font = {"ascent": ascent, "descent": descent, "glyphs": {}}

            for _ in range(num_glyphs):
                code = int.from_bytes(f.read(2), "big")
                width = int.from_bytes(f.read(1), "big")
                height = int.from_bytes(f.read(1), "big")
                xoff = f.read(1)[0]
                xoff = xoff if xoff < 128 else xoff - 256
                yoff = f.read(1)[0]
                yoff = yoff if yoff < 128 else yoff - 256
                x_advance = f.read(1)[0]
                x_advance = x_advance if x_advance < 128 else x_advance - 256
                data_len = int.from_bytes(f.read(1), "big")
                data = list(f.read(data_len))

                font["glyphs"][code] = {
                    "width": width,
                    "height": height,
                    "xoff": xoff,
                    "yoff": yoff,
                    "x_advance": x_advance,
                    "data": data,
                }

        return font

    @micropython.native
    def monospace_digits(self, font):
        digits = [ord(str(i)) for i in range(10)]
        glyphs = font["glyphs"]

        max_width = 0
        for code in digits:
            if code in glyphs:
                max_width = max(max_width, glyphs[code]["width"])

        for code in digits:
            if code not in glyphs:
                continue

            width = glyphs[code]["width"]

            if width < max_width:
                glyphs[code]["width"] = max_width

        return font

    @micropython.native
    def draw_char(self, x, y, char, color, BGcolor, background_mode=0, buffer=0):

        glyph = self.font["glyphs"].get(ord(char))
        if not glyph:
            return 0  # Character not found

        width = glyph["width"]
        height = glyph["height"]
        x_offset = glyph["xoff"]
        y_offset = glyph["yoff"]
        x_advance = glyph["x_advance"]
        bitmap = glyph["data"]
        row_bytes = (width + 7) // 8
        ascent = self.font["ascent"]

        for row in range(height):
            row_start = row * row_bytes
            for byte_idx in range(row_bytes):
                if row_start + byte_idx >= len(bitmap):
                    continue
                byte = bitmap[row_start + byte_idx]
                for bit in range(8):
                    col = byte_idx * 8 + bit
                    if col >= width:
                        break
                    if byte & (1 << (7 - bit)):
                        baseline_y = y + self.font["ascent"]
                        if buffer == 0:

                            self.set_pixel(
                                x + x_offset + col,
                                baseline_y - height - y_offset - ascent + row,
                                color[0],
                                color[1],
                                color[2],
                                0,
                                0,
                                64,
                                64,
                            )
                        else:
                            self.pixel_buffer.append(
                                (
                                    x + x_offset + col - self.text_start[0],
                                    baseline_y
                                    - height
                                    - y_offset
                                    + row
                                    - self.text_start[1]
                                    - ascent,
                                    1,
                                )
                            )  # fg pixel
                    else:
                        if background_mode == 1:
                            baseline_y = y + self.font["ascent"]
                            if buffer == 0:
                                self.set_pixel(
                                    x + x_offset + col,
                                    baseline_y - height - y_offset - ascent + row,
                                    BGcolor[0],
                                    BGcolor[1],
                                    BGcolor[2],
                                    0,
                                    0,
                                    64,
                                    64,
                                )
                            else:

                                self.pixel_buffer.append(
                                    (
                                        x + x_offset + col - self.text_start[0],
                                        baseline_y
                                        - height
                                        - y_offset
                                        + row
                                        - self.text_start[1]
                                        - ascent,
                                        0,
                                    )
                                )  # bg pixel

        return glyph["x_advance"]

    @micropython.native
    def draw_text(
        self,
        x=0,
        y=0,
        text="Hello World",
        color=(255, 255, 255),
        BGcolor=(0, 0, 5),
        background_mode=0,
        buffer=2,
        shadow=0,
        marquee=False,
    ):
        self.scroll_max = 0
        self.text_start = (x, y)
        self.pixel_buffer = []
        if marquee == True and len(text) < 20:
            while len(text) < 20:
                text = text + " " + text
        cx = x
        for ch in text:
            cx += self.draw_char(cx, y, ch, color, BGcolor, background_mode, buffer)
        if background_mode == 2:
            text_surround = self.get_adjacent_pixels(self.pixel_buffer, 0)
            self.pixel_buffer = self.pixel_buffer + list(text_surround)
        if background_mode == 3:
            text_surround = self.get_adjacent_pixels(self.pixel_buffer, 1)
            self.pixel_buffer = self.pixel_buffer + list(text_surround)
        if buffer > 1:
            self.draw_text_buffer(x, y, color, BGcolor, shadow)

    @micropython.viper
    def draw_text_buffer(self, x: int, y: int, color, BGcolor, shadow: int = 0):
        sx: int = 0
        sy: int = 0

        if shadow == 1:
            sx = 1
            sy = 1
        elif shadow == 2:
            sx = 0
            sy = 1
        elif shadow == 3:
            sx = -1
            sy = 1
        elif shadow == 4:
            sx = -1
            sy = 0
        elif shadow == 5:
            sx = -1
            sy = -1
        elif shadow == 6:
            sx = 0
            sy = -1
        elif shadow == 7:
            sx = 1
            sy = -1
        elif shadow == 8:
            sx = 1
            sy = 0

        n: int = int(len(self.pixel_buffer))
        i: int = 0

        if shadow > 0:
            while i < n:
                tup = self.pixel_buffer[i]
                xx: int = int(tup[0])
                yy: int = int(tup[1])
                p: int = int(tup[2])
                if p:
                    self.set_pixel(
                        x + xx + sx,
                        y + yy + sy,
                        int(BGcolor[0]),
                        int(BGcolor[1]),
                        int(BGcolor[2]),
                        0,
                        0,
                        64,
                        64,
                    )
                if x + xx + sx > 64:
                    break
                i += 1

        i = 0
        while i < n:
            tup = self.pixel_buffer[i]
            xx: int = int(tup[0])
            yy: int = int(tup[1])
            p: int = int(tup[2])
            if p:
                self.set_pixel(
                    x + xx,
                    y + yy,
                    int(color[0]),
                    int(color[1]),
                    int(color[2]),
                    0,
                    0,
                    64,
                    64,
                )
            else:
                self.set_pixel(
                    x + xx,
                    y + yy,
                    int(BGcolor[0]),
                    int(BGcolor[1]),
                    int(BGcolor[2]),
                    0,
                    0,
                    64,
                    64,
                )
            if x + xx > 64:
                break
            i += 1

    @micropython.native
    def draw_marquee(self, scroll_x, y_offset, color, BGcolor, VIEWPORT=(0, 0, 64, 64)):
        # Assume pixel_buffer is sorted by x
        x_positions = [xx for xx, yy, p in self.pixel_buffer]  # only once if cached
        start_index = self.find_start_index(x_positions, -scroll_x)

        for i in range(start_index, len(self.pixel_buffer)):
            xx, yy, p = self.pixel_buffer[i]
            screen_x = xx + scroll_x
            if screen_x >= 64:
                break  # done drawing
            if 0 <= screen_x < 64 and p:
                self.set_pixel(
                    screen_x,
                    y_offset + yy,
                    color[0],
                    color[1],
                    color[2],
                    VIEWPORT[0],
                    VIEWPORT[1],
                    VIEWPORT[2],
                    VIEWPORT[3],
                )

    @micropython.native
    def find_start_index(self, x_positions, target):
        """Returns the index of the first element in x_positions >= target"""
        low = 0
        high = len(x_positions)
        while low < high:
            mid = (low + high) // 2
            if x_positions[mid] < target:
                low = mid + 1
            else:
                high = mid
        return low

    @micropython.native
    def scrolling_marquee(
        self, y_position, speed, color, BGcolor, VIEWPORT=(0, 0, 64, 64)
    ):
        DISPLAY_WIDTH = 64
        WRAP_GAP = 10
        WRAP_PIXELS = 150  # How many pixels to wrap from the start

        if self.scroll_max == 0:
            # Sort once
            self.pixel_buffer.sort(key=lambda t: t[0])
            self.scroll_max = self.pixel_buffer[-1][0]  # Since sorted by x

            self.scroll = DISPLAY_WIDTH
            debug_print("New Marquee, max of", self.scroll_max)

            # Wrap first WRAP_PIXELS from beginning
            wrapped = [
                (xx + self.scroll_max + WRAP_GAP, yy, p)
                for xx, yy, p in self.pixel_buffer[:WRAP_PIXELS]
            ]
            self.pixel_buffer.extend(wrapped)

        # Draw buffer at current scroll offset
        self.draw_marquee(self.scroll, y_position, color, BGcolor, VIEWPORT)

        # Reset scroll if end of marquee is reached
        if -self.scroll >= self.scroll_max:
            self.scroll = WRAP_GAP  # Smooth reset

        self.scroll -= speed

    @micropython.native
    def rotate_xy_fast(self, data, angle_deg):
        if angle_deg not in (90, 180, 270):
            raise ValueError("Only 90, 180, 270 degrees supported here")
        rotated = []
        for x, y, v in data:
            if angle_deg == 90:
                rx, ry = -y, x
            elif angle_deg == 180:
                rx, ry = -x, -y
            elif angle_deg == 270:
                rx, ry = y, -x
            rotated.append((rx, ry, v))
        return rotated

    @micropython.native
    def rotate_xy(self, data, angle_deg):
        angle_rad = math.radians(angle_deg)
        cos_a = fast_cos(angle_rad)
        sin_a = fast_sin(angle_rad)

        rotated = []
        for x, y, v in data:
            rx = round(x * cos_a - y * sin_a)
            ry = round(x * sin_a + y * cos_a)
            rotated.append((rx, ry, v))
        return rotated

    @micropython.native
    def flip_xy(self, data, flip_horizontal=False, flip_vertical=False):
        flipped = []
        for x, y, v in data:
            fx = -x if flip_horizontal else x
            fy = -y if flip_vertical else y
            flipped.append((fx, fy, v))
        return flipped
