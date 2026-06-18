import sys, time, select, micropython
from machine import Pin
from hub75 import Hub75

# Recovery window: imports + this sleep run with Ctrl-C still enabled, so after a
# reset mpremote can break in before we disable it for binary transfers below.
time.sleep(2)
micropython.kbd_intr(-1)     # stop intercepting 0x03 (appears in binary image data)

matrix = Hub75(
    data_pin_start=0,
    clock_pin=11,
    latch_pin_start=12,
    row_pin_start=6,
    num_rows=32,
    blocks_per_row=16,
)
matrix.fill(0, 0, 0)
matrix.refresh()

# ---------------------------------------------------------------------------
# Buttons: a falling-edge IRQ debounces and sets a bit in a pending mask.
# The USB write happens in the main loop, never inside the IRQ, so a press
# during an image transfer cannot corrupt anything.
#
# GPIO 0-12 and 15 are claimed by the HUB75 driver (RGB data 0-5, address 6-10,
# clock 11, latch 12, output-enable 15), so the buttons MUST avoid those. These
# four are free on the Pico 2 W. Wire each to GND (internal pull-up, active-low).
# GP19 is intentionally skipped: it's shorted to GP20 on the board, so the press
# is read on GP20 alone. The backup button on GP22 provides NEXT. Each GPIO is
# paired positionally with the BTN code below; the server maps
# BTN:1=PAUSE, 2=NEXT, 3=VOLUME_UP, 4=VOLUME_DOWN.
#   GP18 -> PAUSE/play   GP20 -> VOLUME_DOWN   GP21 -> VOLUME_UP   GP22 -> NEXT
# ---------------------------------------------------------------------------
BTN_GPIOS = (18, 20, 21, 22)
BTN_MSGS = (b"BTN:1\n", b"BTN:4\n", b"BTN:3\n", b"BTN:2\n")
DEBOUNCE_MS = 50

# Polling, NOT edge IRQs: long button wires + weak internal pull-ups let a press
# on one line capacitively glitch its neighbours, and IRQ_FALLING fires on every
# glitch (one press -> a burst across several pins). Sampling the *steady* level
# each loop and requiring it to hold for DEBOUNCE_MS rejects those transients, so
# one press == one message.
_btn_pins = [Pin(g, Pin.IN, Pin.PULL_UP) for g in BTN_GPIOS]
_btn_down = [False] * len(BTN_GPIOS)   # debounced state: currently pressed?
_btn_since = [0] * len(BTN_GPIOS)      # last time raw level matched _btn_down


def poll_buttons():
    now = time.ticks_ms()
    for i in range(len(_btn_pins)):
        raw = _btn_pins[i].value() == 0            # active-low: 0 == pressed
        if raw == _btn_down[i]:
            _btn_since[i] = now                    # stable: reset the hold timer
        elif time.ticks_diff(now, _btn_since[i]) >= DEBOUNCE_MS:
            _btn_down[i] = raw                     # level held long enough: commit
            _btn_since[i] = now
            if raw:                                # emit only on the press edge
                sys.stdout.buffer.write(BTN_MSGS[i])


# ---------------------------------------------------------------------------
# Image input: "IMG:<id>:<size>\n" followed by <size> raw framebuffer bytes.
# Non-blocking poll keeps buttons responsive even when no image is arriving.
# ---------------------------------------------------------------------------
poller = select.poll()
poller.register(sys.stdin, select.POLLIN)
inbuf = bytearray()


def trim(n):
    # MicroPython bytearray has no `del buf[:n]`, so drop consumed bytes by rebind.
    global inbuf
    inbuf = inbuf[n:]


def handle_image(img_id, size):
    while len(inbuf) < size:
        poll_buttons()                       # stay responsive mid-transfer
        if poller.poll(50):
            chunk = sys.stdin.buffer.read(size - len(inbuf))
            if chunk:
                inbuf.extend(chunk)
    data = bytes(inbuf[:size])
    trim(size)

    if len(data) == 8 * 2048:
        matrix.load_framebuffer(data)
        matrix.refresh()
        sys.stdout.buffer.write(b"OK:" + img_id + b"\n")
    else:
        sys.stdout.buffer.write(b"ERR:" + img_id + b"\n")


def try_consume():
    nl = inbuf.find(b"\n")
    if nl < 0:
        return
    header = bytes(inbuf[:nl])
    trim(nl + 1)
    if not header.startswith(b"IMG:"):
        return                                # ignore anything that isn't a frame
    parts = header.split(b":")
    if len(parts) == 3:
        handle_image(parts[1], int(parts[2]))


while True:
    # Never fall through to the REPL: a stray error must not turn the data
    # stream into a Python prompt that eats the next image as keystrokes.
    try:
        poll_buttons()
        if poller.poll(10):
            chunk = sys.stdin.buffer.read(4096)
            if chunk:
                inbuf.extend(chunk)
                try_consume()
    except Exception:
        inbuf = bytearray()
