
from hub75 import Hub75
import time

matrix = Hub75(
    data_pin_start=0,
    clock_pin=11,
    latch_pin_start=12,
    row_pin_start=6,
    num_rows=32,
    blocks_per_row=16
)


# Load and draw image once
matrix.load_bmp("image.bmp", x1=0, y1=0,brightness=0.5)

# Keep refreshing the display
while True:
    matrix.refresh()
    thread.sleep(0.1)