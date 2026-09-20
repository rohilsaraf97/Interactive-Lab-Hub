import time
import subprocess
import digitalio
import board
from PIL import Image, ImageDraw, ImageFont

import adafruit_rgb_display.st7789 as st7789

# stop the boot-time screen service so it doesn't fight over the display
subprocess.run(["sudo", "systemctl", "stop", "piscreen.service", "--now"])

# --- display setup (same as your working config) ---
cs_pin = digitalio.DigitalInOut(board.D5)
dc_pin = digitalio.DigitalInOut(board.D25)
reset_pin = None
BAUDRATE = 64000000
spi = board.SPI()

display = st7789.ST7789(
    spi, cs=cs_pin, dc=dc_pin, rst=reset_pin, baudrate=BAUDRATE,
    width=135, height=240, x_offset=53, y_offset=40,
)

backlight = digitalio.DigitalInOut(board.D22)
backlight.switch_to_output(value=True)

buttonA = digitalio.DigitalInOut(board.D23)
buttonB = digitalio.DigitalInOut(board.D24)
buttonA.switch_to_input(pull=digitalio.Pull.UP)
buttonB.switch_to_input(pull=digitalio.Pull.UP)

WIDTH = display.width
HEIGHT = display.height
font = ImageFont.load_default()

# --- placeholder state, wire up to real logic later ---
total_snacks = 3
snacks_had = 0
snacks_remaining = total_snacks
day_progress = 0.0  # recalculated every loop iteration, see below


def compute_day_progress():
    from datetime import datetime
    now = datetime.now()
    seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
    return seconds_since_midnight / 86400  # 0 to 1


def draw_default_screen():
    image = Image.new("RGB", (WIDTH, HEIGHT), (30, 30, 60))
    draw = ImageDraw.Draw(image)
    OUTPUT = time.strftime("%m/%d/%Y %H:%M:%S")
    # placeholder ascii/emoji face, swap for real Buddy art later
    # draw.text((WIDTH // 2 - 20, HEIGHT // 2 - 10), "(^_^)", font=font, fill=(255, 255, 255))
    draw.text((WIDTH // 2 - 40, HEIGHT // 2 + 10), OUTPUT, font=font, fill=(255, 255, 255))
    display.image(image)


def draw_status_screen():
    image = Image.new("RGB", (WIDTH, HEIGHT), (20, 20, 20))
    draw = ImageDraw.Draw(image)

    if snacks_had == 0:
        draw.text((10, HEIGHT // 2 - 20), "no snacks yet", font=font, fill=(255, 255, 255))
        draw.text((10, HEIGHT // 2), "start snacking!", font=font, fill=(255, 255, 255))
    else:
        # dots: filled = had, empty = remaining
        dot_r = 6
        gap = 20
        start_x = 15
        y = HEIGHT // 2 - 30
        for i in range(snacks_had):
            x = start_x + i * gap
            draw.ellipse((x, y, x + dot_r * 2, y + dot_r * 2), fill=(0, 255, 120))
        for i in range(snacks_remaining):
            x = start_x + (snacks_had + i) * gap
            draw.ellipse((x, y, x + dot_r * 2, y + dot_r * 2), outline=(150, 150, 150))

    # day progress bar (always shown)
    bar_x, bar_y = 10, HEIGHT - 30
    bar_w, bar_h = WIDTH - 20, 10
    draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), outline=(200, 200, 200))
    fill_w = int(bar_w * day_progress)
    draw.rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), fill=(80, 160, 255))

    display.image(image)


while True:
    day_progress = compute_day_progress()  # update every iteration
    b_pressed = (buttonB.value == False)

    if b_pressed:
        draw_status_screen()
    else:
        draw_default_screen()

    time.sleep(0.05)