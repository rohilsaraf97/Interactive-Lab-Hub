import time
import subprocess
import digitalio
import board
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageSequence

import adafruit_rgb_display.st7789 as st7789

# ============================================================
# CONFIG — fixed meal schedule (placeholder times, change anytime)
# ============================================================
TEST_MODE = True  # set False for real schedule — True compresses everything for demo/video

if TEST_MODE:
    TEST_START = time.monotonic()
    TEST_DAY_LENGTH_SECONDS = 65  # whole virtual "day" loops every 65s
    # (start_sec, end_sec) within the virtual day, in seconds — real gaps included
    MEALS = {
        "breakfast": (10 / 60, 20 / 60),
        "lunch": (30 / 60, 40 / 60),
        "dinner": (50 / 60, 60 / 60),
    }
    APPROACH_MINUTES = 5 / 60  # 5 seconds
else:
    # (start_minute, end_minute) in minutes-since-midnight
    MEALS = {
        "breakfast": (8 * 60, 9 * 60),
        "lunch": (12 * 60, 13 * 60),
        "dinner": (18 * 60, 19 * 60),
    }
    APPROACH_MINUTES = 20

MEAL_ORDER = ["breakfast", "lunch", "dinner"]  # chronological
MAX_SNACKS_PER_GAP = 2

# gap name -> which meal's approach window ends the gap
# (post_dinner is the overnight/sleep gap, ending at breakfast's approach)
GAPS = {
    "post_breakfast": MEALS["breakfast"][1],  # gap starts right after breakfast closes
    "post_lunch": MEALS["lunch"][1],
    "post_dinner": MEALS["dinner"][1],
}

ROTATION_DEGREES = 90  # 0/90/180/270 — flip if orientation looks wrong

MESSAGE_BG = (15, 15, 20)
MESSAGE_FG = (255, 255, 255)
MESSAGE_DURATION = 2.0

# placeholder gif paths — swap with real assets later
GIF_PATHS = {
    "breakfast_approaching": "assets/approaching.gif",
    "breakfast_open": "assets/breakfast.gif",
    "lunch_approaching": "assets/approaching.gif",
    "lunch_open": "assets/lunch.gif",
    "dinner_approaching": "assets/approaching.gif",
    "dinner_open": "assets/dinner.gif",
    "waiting": "assets/sad.gif",
    "sleeping": "assets/sleeping.gif",
    "snack_logged": "assets/snack_logged.gif",
}

FALLBACK_COLORS = {
    "breakfast_approaching": (200, 160, 60),
    "breakfast_open": (255, 200, 80),
    "lunch_approaching": (200, 140, 60),
    "lunch_open": (255, 190, 70),
    "dinner_approaching": (150, 80, 90),
    "dinner_open": (200, 100, 110),
    "waiting": (60, 70, 100),
    "sleeping": (20, 20, 50),
    "snack_logged": (80, 200, 120),
}

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

PANEL_WIDTH = display.width
PANEL_HEIGHT = display.height

# drawn in landscape; show() rotates into the panel's native buffer
WIDTH = 240
HEIGHT = 135

# ============================================================
# FONTS
# ============================================================
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
try:
    FONT_LARGE = ImageFont.truetype(FONT_PATH, 24)
    FONT_MED = ImageFont.truetype(FONT_PATH, 16)
    FONT_SMALL = ImageFont.truetype(FONT_PATH, 12)
except Exception:
    FONT_LARGE = ImageFont.load_default()
    FONT_MED = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()


def centered_text(draw, text, font, y, fill):
    """Handles multi-line text (\n) by centering each line individually."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        draw.text(((WIDTH - w) // 2, y + i * (h + 6)), line, font=font, fill=fill)


# ============================================================
# STATE
# ============================================================
current_day = datetime.now().date()
test_day_index = 0  # which virtual "day" we're on, only used in TEST_MODE
meal_logged = {name: False for name in MEAL_ORDER}
snack_count_per_gap = {gap: 0 for gap in GAPS}

message_text = None
message_until = 0.0
message_gif_key = None  # set when a message should play a gif behind the text
prev_a_pressed = False

last_state = None  # (kind, name) — used to detect gap transitions for snack reset


# ============================================================
# SCHEDULE / STATE MACHINE
# ============================================================
def minutes_now():
    if TEST_MODE:
        elapsed_min = (time.monotonic() - TEST_START) / 60.0
        day_len_min = TEST_DAY_LENGTH_SECONDS / 60.0
        return elapsed_min % day_len_min
    now = datetime.now()
    return now.hour * 60 + now.minute + now.second / 60.0


def get_state():
    """Returns (kind, name):
    kind = 'meal_open' | 'approaching' | 'gap'
    name = meal name, or gap name if kind == 'gap'
    """
    m = minutes_now()

    for name in MEAL_ORDER:
        start, end = MEALS[name]
        if start <= m < end:
            return ("meal_open", name)
        if (start - APPROACH_MINUTES) <= m < start:
            return ("approaching", name)

    # not in any meal or approach window -> figure out which gap we're in
    b_start, b_end = MEALS["breakfast"]
    l_start, l_end = MEALS["lunch"]
    d_start, d_end = MEALS["dinner"]

    if b_end <= m < (l_start - APPROACH_MINUTES):
        return ("gap", "post_breakfast")
    if l_end <= m < (d_start - APPROACH_MINUTES):
        return ("gap", "post_lunch")
    # overnight: from dinner close until breakfast's approach window next day
    return ("gap", "post_dinner")


def reset_if_new_day():
    """Real mode: resets at actual midnight. Test mode: resets every time
    the looping virtual day wraps around, so you can watch a full
    reset happen live within the demo."""
    global current_day, test_day_index, meal_logged

    if TEST_MODE:
        day_len_min = TEST_DAY_LENGTH_SECONDS / 60.0
        elapsed_min = (time.monotonic() - TEST_START) / 60.0
        idx = int(elapsed_min // day_len_min)
        if idx != test_day_index:
            test_day_index = idx
            meal_logged = {name: False for name in MEAL_ORDER}
    else:
        today = datetime.now().date()
        if today != current_day:
            current_day = today
            meal_logged = {name: False for name in MEAL_ORDER}


def handle_gap_transition(state):
    """Reset a gap's snack counter the moment we freshly enter it."""
    global last_state
    kind, name = state
    if kind == "gap" and (last_state is None or last_state != state):
        if last_state is None or last_state[1] != name:
            snack_count_per_gap[name] = 0
    last_state = state


def compute_day_progress():
    if TEST_MODE:
        day_len_min = TEST_DAY_LENGTH_SECONDS / 60.0
        return minutes_now() / day_len_min
    now = datetime.now()
    return (now.hour * 3600 + now.minute * 60 + now.second) / 86400


def meals_had_count():
    return sum(1 for v in meal_logged.values() if v)


def meals_expired_count():
    m = minutes_now()
    count = 0
    for name in MEAL_ORDER:
        _, end = MEALS[name]
        if m >= end and not meal_logged[name]:
            count += 1
    return count


def total_snacks_had():
    return sum(snack_count_per_gap.values())


# ============================================================
# GIF PLAYBACK
# ============================================================
gif_cache = {}
current_gif_key = None
current_frame_index = 0
next_frame_time = 0.0


def load_gif_frames(key):
    if key in gif_cache:
        return gif_cache[key]

    path = GIF_PATHS.get(key)
    frames = []
    try:
        img = Image.open(path)
        for frame in ImageSequence.Iterator(img):
            f = frame.convert("RGB").resize((WIDTH, HEIGHT))
            duration = frame.info.get("duration", 100) / 1000.0
            frames.append((f, duration))
    except Exception:
        image = Image.new("RGB", (WIDTH, HEIGHT), FALLBACK_COLORS.get(key, (40, 40, 40)))
        draw = ImageDraw.Draw(image)
        centered_text(draw, f"[{key}]", FONT_MED, HEIGHT // 2 - 10, (255, 255, 255))
        frames = [(image, 1.0)]

    gif_cache[key] = frames
    return frames


def get_current_gif_frame(key):
    global current_gif_key, current_frame_index, next_frame_time

    frames = load_gif_frames(key)

    if key != current_gif_key:
        current_gif_key = key
        current_frame_index = 0
        next_frame_time = time.monotonic() + frames[0][1]
        return frames[0][0].copy()

    if time.monotonic() >= next_frame_time:
        current_frame_index = (current_frame_index + 1) % len(frames)
        next_frame_time = time.monotonic() + frames[current_frame_index][1]

    return frames[current_frame_index][0].copy()


def gif_key_for_state(state):
    kind, name = state
    if kind in ("meal_open", "approaching"):
        suffix = "open" if kind == "meal_open" else "approaching"
        return f"{name}_{suffix}"
    # gap
    if name == "post_dinner":
        return "sleeping"
    return "waiting"


# ============================================================
# SCREENS
# ============================================================
def show(image):
    if ROTATION_DEGREES:
        image = image.rotate(ROTATION_DEGREES, expand=True)
    image = image.resize((PANEL_WIDTH, PANEL_HEIGHT))
    display.image(image)


def text_fits(draw, text, font, max_width):
    for line in text.split("\n"):
        bbox = draw.textbbox((0, 0), line, font=font)
        if (bbox[2] - bbox[0]) > max_width:
            return False
    return True


def choose_font(draw, text, max_width):
    for font in (FONT_LARGE, FONT_MED, FONT_SMALL):
        if text_fits(draw, text, font, max_width):
            return font
    return FONT_SMALL  # smallest option, even if it still doesn't fully fit


def draw_message_screen(text, gif_key=None):
    if gif_key:
        image = get_current_gif_frame(gif_key)
    else:
        image = Image.new("RGB", (WIDTH, HEIGHT), MESSAGE_BG)

    draw = ImageDraw.Draw(image)

    max_text_width = WIDTH - 20  # small side margin
    font = choose_font(draw, text, max_text_width)
    line_height = font.size + 6 if hasattr(font, "size") else 22
    line_count = text.count("\n") + 1
    start_y = HEIGHT // 2 - (line_count * line_height) // 2

    # readable text over a gif: dark strip behind it
    if gif_key:
        strip_h = line_count * line_height + 10
        draw.rectangle((0, start_y - 5, WIDTH, start_y - 5 + strip_h), fill=(0, 0, 0))

    centered_text(draw, text, font, start_y, MESSAGE_FG)
    show(image)


def draw_default_screen(state):
    if message_text and time.monotonic() < message_until:
        draw_message_screen(message_text, message_gif_key)
        return

    key = gif_key_for_state(state)
    image = get_current_gif_frame(key)
    show(image)


def draw_status_screen():
    image = Image.new("RGB", (WIDTH, HEIGHT), (18, 18, 22))
    draw = ImageDraw.Draw(image)

    had = meals_had_count()
    expired = meals_expired_count()
    snacks = total_snacks_had()

    centered_text(draw, f"Meals: {had} had, {expired} missed / 3", FONT_MED, 15, (255, 255, 255))
    centered_text(draw, f"Snacks today: {snacks}", FONT_MED, 40, (255, 255, 255))

    # small per-meal dots: green = logged, red = expired, gray = pending
    dot_r = 8
    gap = 40
    start_x = (WIDTH - (len(MEAL_ORDER) * gap - (gap - dot_r * 2))) // 2
    y = 70
    m = minutes_now()
    for i, name in enumerate(MEAL_ORDER):
        _, end = MEALS[name]
        if meal_logged[name]:
            color = (60, 220, 140)
        elif m >= end:
            color = (220, 70, 70)
        else:
            color = (120, 120, 120)
        x = start_x + i * gap
        draw.ellipse((x, y, x + dot_r * 2, y + dot_r * 2), fill=color)

    bar_x, bar_y = 15, HEIGHT - 22
    bar_w, bar_h = WIDTH - 30, 12
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=6, outline=(180, 180, 180), width=2)
    fill_w = int(bar_w * compute_day_progress())
    if fill_w > 4:
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=6, fill=(90, 170, 255))

    show(image)


# ============================================================
# BUTTON A LOGIC
# ============================================================
def handle_button_a(state):
    global message_text, message_until, message_gif_key
    kind, name = state
    message_gif_key = None  # default: plain background unless a case below sets a gif

    if kind == "meal_open":
        if not meal_logged[name]:
            meal_logged[name] = True
            message_text = f"{name} logged!"
        else:
            message_text = f"{name} \nalready logged"

    elif kind == "approaching":
        message_text = f"Don't snack! \n{name} approaching"

    elif kind == "gap":
        if snack_count_per_gap[name] < MAX_SNACKS_PER_GAP:
            snack_count_per_gap[name] += 1
            message_text = f"Snack logged ({snack_count_per_gap[name]}/{MAX_SNACKS_PER_GAP})"
            message_gif_key = "snack_logged"
        else:
            message_text = "no more snacks till next meal"

    message_until = time.monotonic() + MESSAGE_DURATION


# ============================================================
# MAIN LOOP
# ============================================================
while True:
    reset_if_new_day()
    state = get_state()
    handle_gap_transition(state)

    a_pressed = (buttonA.value == False)
    b_pressed = (buttonB.value == False)

    if a_pressed and not prev_a_pressed:
        handle_button_a(state)
    prev_a_pressed = a_pressed

    if b_pressed:
        draw_status_screen()
    else:
        draw_default_screen(state)

    time.sleep(0.05)