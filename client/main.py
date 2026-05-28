
from hub75 import Hub75

matrix = Hub75(
    data_pin_start=0,
    clock_pin=11,
    latch_pin_start=12,
    row_pin_start=6,
    num_rows=32,
    blocks_per_row=16
)

matrix.fill(0, 255, 0)
matrix.refresh()

import time

import select
import sys

poller_in = select.poll()
poller_in.register(sys.stdin, select.POLLIN)

poller_out = select.poll()
poller_out.register(sys.stdout, select.POLLOUT)


# buf = "OK"
# while True:
#   poller_out
#   sys.stdout.write(buf)
#   time.sleep(1)

buf = ""
print("ready")

while True:
  if poller.poll(0):
    buf += sys.stdin.read(1)
    if buf.endswith("\n"):
      msg = buf.strip()
      buf = ""
      print("got:", msg)
      print(msg)
      print(msg == "HELLO")
      if msg == "HELLO":
        matrix.fill(255, 0, 0)
        matrix.refresh()
  time.sleep(0.01)
