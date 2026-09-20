import time
import subprocess
import digitalio
import board
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageSequence

import adafruit_rgb_display.st7789 as st7789

# ============================================================
# CONFIG
# ============================================================
SNACK_INTERVAL_SECONDS = 30  # TESTING VALUE. Set to 6 * 3600 for real use.

# Rotate the landscape canvas into the panel's native portrait buffer.
# Try 90 first; if it's backwards/mirrored, switch to 270.
ROTATION_DEGREES = 90

# stage boundaries as fraction of SNACK_INTERVAL_SECONDS elapsed since last snack
STAGE_BOUNDS = {
    "content": (0.0, 0.15),
    "sleepy": (0.15, 0.5),
    "curious": (0.5, 0.75),
    "shocked": (0.75, 0.95),
    "starstruck": (0.95, 1.15),   # window open
    "winding_down": (1.15, 1.3),  # window closing
    # anything past 1.3 stays "winding_down" until next snack
}

STAGE_MESSAGES = {
    "content": "just snacked",
    "sleepy": "not yet",
    "curious": "getting close",
    "shocked": "almost time!",
    "starstruck": "snack now!",
    "winding_down": "closing soon",
}

CONFIRM_MESSAGE = "confirmed!"

STAGE_GIFS = {
    "ready": "assets/active.gif",
    "content": "assets/happy.gif",
    "sleepy": "assets/sleepy.gif",
    "curious": "assets/breakfast.gif",
    "shocked": "assets/lunch.gif",
    "starstruck": "assets/sad.gif",
    "winding_down": "assets/sleeping.gif",
}

STAGE_COLORS = {
    "ready": (60, 140, 90),
    "content": (50, 70, 100),
    "sleepy": (50, 70, 100),
    "curious": (160, 120, 30),
    "shocked": (150, 50, 30),
    "starstruck": (180, 180, 30),
    "winding_down": (120, 90, 40),
}

MESSAGE_BG = (15, 15, 20)
MESSAGE_FG = (255, 255, 255)
MESSAGE_DURATION = 2.0  # seconds the message screen stays up after button A

# ============================================================
# HARDWARE SETUP
# ============================================================
subprocess.run(["sudo", "systemctl", "stop", "piscreen.service", "--now"])

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

# panel's native (physical) buffer size — what display.image() expects
PANEL_WIDTH = display.width
PANEL_HEIGHT = display.height

# everything is DRAWN in landscape; show() rotates it into the panel buffer
WIDTH = 240
HEIGHT = 135

# ============================================================
# FONTS
# ============================================================
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
try:
    FONT_LARGE = ImageFont.truetype(FONT_PATH, 26)
    FONT_MED = ImageFont.truetype(FONT_PATH, 16)
    FONT_SMALL = ImageFont.truetype(FONT_PATH, 13)
except Exception:
    FONT_LARGE = ImageFont.load_default()
    FONT_MED = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()


def centered_text(draw, text, font, y, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((WIDTH - w) // 2, y), text, font=font, fill=fill)


# ============================================================
# STATE
# ============================================================
last_snack_time = None      # datetime, anchor. None = no snack yet today
snack_times_today = []      # list of datetimes
current_day = datetime.now().date()

message_text = None
message_until = 0.0         # time.monotonic() timestamp

prev_a_pressed = False


# ============================================================
# HELPERS
# ============================================================
def reset_if_new_day():
    global last_snack_time, snack_times_today, current_day
    today = datetime.now().date()
    if today != current_day:
        current_day = today
        last_snack_time = None
        snack_times_today = []


def get_stage():
    """Returns 'ready' if no snack yet today, else current stage name."""
    if last_snack_time is None:
        return "ready"
    elapsed = (datetime.now() - last_snack_time).total_seconds()
    frac = elapsed / SNACK_INTERVAL_SECONDS
    for stage, (lo, hi) in STAGE_BOUNDS.items():
        if lo <= frac < hi:
            return stage
    return "winding_down"  # past the window, still waiting on a snack


def window_is_open():
    stage = get_stage()
    return stage == "ready" or stage == "starstruck"


def confirm_snack():
    global last_snack_time, snack_times_today
    now = datetime.now()
    last_snack_time = now
    snack_times_today.append(now)


def compute_snacks_remaining():
    """How many more full intervals fit between now and midnight."""
    anchor = last_snack_time if last_snack_time else datetime.now()
    midnight = datetime.combine(current_day + timedelta(days=1), datetime.min.time())
    remaining_seconds = (midnight - anchor).total_seconds()
    return max(0, int(remaining_seconds // SNACK_INTERVAL_SECONDS))


def compute_day_progress():
    now = datetime.now()
    seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
    return seconds_since_midnight / 86400


# ============================================================
# GIF PLAYBACK
# ============================================================
gif_cache = {}          # stage -> list of (frame_image, duration_seconds)
current_gif_stage = None
current_frame_index = 0
next_frame_time = 0.0


def load_gif_frames(stage):
    if stage in gif_cache:
        return gif_cache[stage]

    path = STAGE_GIFS.get(stage)
    frames = []
    try:
        img = Image.open(path)
        for frame in ImageSequence.Iterator(img):
            f = frame.convert("RGB").resize((WIDTH, HEIGHT))
            duration = frame.info.get("duration", 100) / 1000.0
            frames.append((f, duration))
    except Exception:
        image = Image.new("RGB", (WIDTH, HEIGHT), STAGE_COLORS.get(stage, (40, 40, 40)))
        draw = ImageDraw.Draw(image)
        centered_text(draw, f"[{stage}]", FONT_MED, HEIGHT // 2 - 10, (255, 255, 255))
        frames = [(image, 1.0)]

    gif_cache[stage] = frames
    return frames


def get_current_gif_frame(stage):
    global current_gif_stage, current_frame_index, next_frame_time

    frames = load_gif_frames(stage)

    if stage != current_gif_stage:
        current_gif_stage = stage
        current_frame_index = 0
        next_frame_time = time.monotonic() + frames[0][1]
        return frames[0][0].copy()

    if time.monotonic() >= next_frame_time:
        current_frame_index = (current_frame_index + 1) % len(frames)
        next_frame_time = time.monotonic() + frames[current_frame_index][1]

    return frames[current_frame_index][0].copy()


# ============================================================
# SCREENS
# ============================================================
def show(image):
    """All screens funnel through here — rotate the landscape canvas into
    the panel's native buffer size right before sending."""
    if ROTATION_DEGREES:
        image = image.rotate(ROTATION_DEGREES, expand=True)
    image = image.resize((PANEL_WIDTH, PANEL_HEIGHT))
    display.image(image)


def draw_message_screen(text):
    """Big, clean full-screen message — used for button A feedback.
    Replaces the gif entirely rather than overlaying it."""
    image = Image.new("RGB", (WIDTH, HEIGHT), MESSAGE_BG)
    draw = ImageDraw.Draw(image)
    centered_text(draw, text, FONT_LARGE, HEIGHT // 2 - 15, MESSAGE_FG)
    show(image)


def draw_default_screen():
    if message_text and time.monotonic() < message_until:
        draw_message_screen(message_text)
        return

    stage = get_stage()
    image = get_current_gif_frame(stage)
    show(image)


def draw_status_screen():
    image = Image.new("RGB", (WIDTH, HEIGHT), (18, 18, 22))
    draw = ImageDraw.Draw(image)

    snacks_had = len(snack_times_today)
    snacks_remaining = compute_snacks_remaining()

    if snacks_had == 0:
        centered_text(draw, "no snacks yet", FONT_MED, 30, (255, 255, 255))
        centered_text(draw, "start snacking!", FONT_MED, 55, (255, 255, 255))
    else:
        centered_text(draw, f"{snacks_had} had  ·  {snacks_remaining} left", FONT_MED, 15, (255, 255, 255))

        dot_r = 10
        gap = 34
        total_dots = snacks_had + snacks_remaining
        start_x = (WIDTH - (total_dots * gap - (gap - dot_r * 2))) // 2
        y = 48

        for i in range(snacks_had):
            x = start_x + i * gap
            draw.ellipse((x, y, x + dot_r * 2, y + dot_r * 2), fill=(60, 220, 140))
        for i in range(snacks_remaining):
            x = start_x + (snacks_had + i) * gap
            draw.ellipse((x, y, x + dot_r * 2, y + dot_r * 2), outline=(160, 160, 160), width=2)

    bar_x, bar_y = 15, HEIGHT - 25
    bar_w, bar_h = WIDTH - 30, 14
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=7, outline=(180, 180, 180), width=2)
    fill_w = int(bar_w * compute_day_progress())
    if fill_w > 4:
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=7, fill=(90, 170, 255))

    show(image)


# ============================================================
# MAIN LOOP
# ============================================================
while True:
    reset_if_new_day()

    a_pressed = (buttonA.value == False)
    b_pressed = (buttonB.value == False)

    # edge-detect A: only act on the moment it's newly pressed
    if a_pressed and not prev_a_pressed:
        if window_is_open():
            confirm_snack()
            message_text = CONFIRM_MESSAGE
        else:
            message_text = STAGE_MESSAGES.get(get_stage(), "")
        message_until = time.monotonic() + MESSAGE_DURATION
    prev_a_pressed = a_pressed

    if b_pressed:
        draw_status_screen()
    else:
        draw_default_screen()

    time.sleep(0.05)