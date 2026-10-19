#!/usr/bin/env python3
"""
Tea Bag Dunker - Lab 4 (Feast Automata)

1. Put your mug on the base. The distance sensor under it notices the mug.
2. Turn the knob to pick tea strength. The knob's light shows the strength.
3. Press the knob to start. The servo lowers the bag and dunks it.
   The light fades green -> orange -> brown as time runs out.
4. When time is up, the arm lifts the bag out and the light blinks.
5. Lift the mug (or press the knob) at any time to stop and lift the bag.

Run:
    python tea_dunker.py              # normal (2 to 6 minute steeps)
    python tea_dunker.py --demo       # 10x faster, good for filming
"""
import argparse
import time

import board
import pi_servo_hat
import qwiic_proximity
from adafruit_seesaw import digitalio, neopixel, rotaryio, seesaw

SERVO_CHANNEL = 0
UP_ANGLE = 0          # arm up, bag out of the mug
DOWN_ANGLE = 60       # arm down, bag in the tea
DIP = 30              # how many degrees the arm lifts for each dunk

MUG_THRESHOLD = 1000  # reading above this = mug is on the base
ENCODER_DIRECTION = 1  # flip to -1 if turning right makes the tea weaker
DEMO_SPEEDUP = 10     # --demo makes steeping this many times faster

STRENGTHS = [
    ("very weak",   120, (255, 230, 120), 8.0, 0.030),
    ("weak",        180, (255, 190, 60),  6.0, 0.025),
    ("medium",      240, (220, 120, 20),  4.0, 0.020),
    ("strong",      300, (150, 60, 10),   2.5, 0.010),
    ("very strong", 360, (90, 20, 0),     1.5, 0.005),
]

GREEN, ORANGE, BROWN = (0, 255, 0), (255, 120, 0), (120, 40, 0)
OFF, WHITE = (0, 0, 0), (60, 60, 60)

# ---------------- Hardware setup ----------------
i2c = board.I2C()

# Rotary encoder + its button + its NeoPixel (address 0x36)
ss = seesaw.Seesaw(i2c, addr=0x36)
encoder = rotaryio.IncrementalEncoder(ss)
ss.pin_mode(24, ss.INPUT_PULLUP)
button = digitalio.DigitalIO(ss, 24)
pixel = neopixel.NeoPixel(ss, 6, 1)
pixel.brightness = 0.5

# Distance sensor under the mug (address 0x60)
prox = qwiic_proximity.QwiicProximity()
if not prox.begin():
    raise SystemExit("Distance sensor not found. Check the Qwiic cable (run i2cdetect -y 1).")

# Servo pHAT (address 0x40)
hat = pi_servo_hat.PiServoHat()
hat.restart()
current_angle = UP_ANGLE
hat.move_servo_position(SERVO_CHANNEL, UP_ANGLE, 180)


# ---------------- Small helpers ----------------
def knob():
    return ENCODER_DIRECTION * encoder.position


def pressed():
    return not button.value  # the button reads False when pressed


def wait_release():
    while pressed():
        time.sleep(0.01)


def mug_present():
    """Average a few readings so one bad reading doesn't count."""
    total = 0
    for _ in range(3):
        total += prox.get_proximity()
        time.sleep(0.01)
    return total / 3 > MUG_THRESHOLD


def mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def steep_color(t):
    """0 = green, 0.5 = orange, 1 = brown."""
    if t < 0.5:
        return mix(GREEN, ORANGE, t * 2)
    return mix(ORANGE, BROWN, (t - 0.5) * 2)


def move_to(target, step_delay=0.02):
    """Move the servo slowly so the wet bag doesn't fly off."""
    global current_angle
    step = 2 if target > current_angle else -2
    for angle in range(int(current_angle), int(target), step):
        hat.move_servo_position(SERVO_CHANNEL, angle, 180)
        time.sleep(step_delay)
    hat.move_servo_position(SERVO_CHANNEL, target, 180)
    current_angle = target


def dip_angle():
    """Dunk toward the UP side, whichever direction that is on your build."""
    return DOWN_ANGLE + DIP if UP_ANGLE > DOWN_ANGLE else DOWN_ANGLE - DIP


# ---------------- The tea steps ----------------
def wait_for_mug():
    print("\nWaiting for a mug...")
    pixel.fill(OFF)
    while not mug_present():
        time.sleep(0.1)
    print("Mug found!")
    # little "hello" flash so you know it noticed
    for _ in range(2):
        pixel.fill(WHITE)
        time.sleep(0.15)
        pixel.fill(OFF)
        time.sleep(0.15)


def choose_strength(level):
    """Returns the chosen level, or None if the mug was taken away."""
    print("Turn the knob to pick strength, press to start.")
    last, shown = knob(), None
    while True:
        if not mug_present():
            print("Mug removed.")
            return None
        if knob() != last:
            level = max(0, min(len(STRENGTHS) - 1, level + (knob() - last)))
            last = knob()
        if level != shown:
            name, secs, color, _, _ = STRENGTHS[level]
            pixel.fill(color)
            print(f"  Strength: {name} ({secs // 60} min)")
            shown = level
        if pressed():
            wait_release()
            return level
        time.sleep(0.03)


def steep(level, demo):
    """Returns True if it finished, False if stopped early."""
    name, secs, _, dunk_every, speed = STRENGTHS[level]
    if demo:
        secs /= DEMO_SPEEDUP
    print(f"Steeping '{name}' for {secs:.0f} s. Lift the mug or press the knob to stop.")

    pixel.fill(GREEN)
    move_to(DOWN_ANGLE, speed)
    start = last_dunk = time.monotonic()

    while True:
        elapsed = time.monotonic() - start
        if elapsed >= secs:
            finished = True
            break
        if pressed() or not mug_present():
            wait_release()
            print("\nStopped early.")
            finished = False
            break

        pixel.fill(steep_color(elapsed / secs))
        if time.monotonic() - last_dunk >= dunk_every:
            move_to(dip_angle(), speed)
            move_to(DOWN_ANGLE, speed)
            last_dunk = time.monotonic()

        print(f"  {int(secs - elapsed)} s left   ", end="\r")
        time.sleep(0.05)

    move_to(UP_ANGLE, 0.02)  # lift the bag out to drip
    return finished


def tea_ready():
    print("\nTea is ready! Take your mug (or press the knob).")
    on = True
    while mug_present() and not pressed():
        pixel.fill(BROWN if on else OFF)
        on = not on
        time.sleep(0.4)
    wait_release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="10x faster steeping")
    args = parser.parse_args()

    try:
        level = 2
        while True:
            wait_for_mug()
            chosen = choose_strength(level)
            if chosen is None:
                continue
            level = chosen
            if steep(level, args.demo):
                tea_ready()
            pixel.fill(OFF)
            while mug_present():
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nBye!")
    finally:
        move_to(UP_ANGLE, 0.01)
        pixel.fill(OFF)


if __name__ == "__main__":
    main()