"""
Dish Shame: the whole night, from bedtime to the morning report.

  1. Before bed: clean the counter and press the button. The device checks the counter,
     says goodnight, dims its light and turns the screen off.
  2. Overnight: one look every 15 s. A line goes into the night log only when the dishes
     (or a person at the counter) change. A heartbeat line every 10 minutes.
  3. Morning: press the button (or wait for --wake). The screen, the voice and the
     SHAME flag tell you what showed up overnight.

    python dish_shame.py                         # the real thing (start it in tmux, see the README)
    python dish_shame.py --wake 07:30            # also end the night by itself at 7:30
    python dish_shame.py --fake 60 --interval 5  # a one-minute fake night to test it
    python dish_shame.py --source testpics/      # replay a folder of photos instead of the webcam
    python dish_shame.py --once                  # stop after one morning instead of starting over

Each night is saved to nights/night_<date>-<time>.jsonl and copied to night_log.jsonl,
so the class's morning.py works on it too.
"""
import argparse
import datetime
import json
import pathlib
import shutil
import signal
import subprocess
import time

import cv2

from dish_detect import Camera, annotate, describe, look, total
from dish_hw import Button, Flag, Screen, speak
from dish_report import morning_report

HERE = pathlib.Path(__file__).parent
RED, GREEN, BLUE = (255, 80, 80), (110, 255, 110), (120, 200, 255)
PROOF_SECONDS = 10      # how long the "proof" photo stays on the screen after a change
CHECK_SECONDS = 5       # how long the regular "still working" checkpoint photo stays on

parser = argparse.ArgumentParser()
parser.add_argument("--source", default="0", help="webcam number, a photo, or a folder of photos")
parser.add_argument("--interval", type=float, default=15, help="seconds between looks")
parser.add_argument("--wake", help="end the night by itself at this time, e.g. 07:30")
parser.add_argument("--fake", type=float, help="end the night after this many seconds (testing)")
parser.add_argument("--model", default="qwen3.5:0.8b")
parser.add_argument("--no-qwen", action="store_true", help="plain template report, no language model")
parser.add_argument("--once", action="store_true", help="stop after one morning")
parser.add_argument("--no-snaps", action="store_true", help="don't save photos when the dishes change")
parser.add_argument("--auto", action="store_true", help="testing: press the button automatically")
parser.add_argument("--check", type=float, default=60,
                    help="show a checkpoint photo this often (seconds) even if nothing changed; 0 = off")
args = parser.parse_args()

screen, button, flag, cam = Screen(), Button(auto=args.auto), Flag(), Camera(args.source)


def on_stop(*_):
    raise KeyboardInterrupt      # `systemctl stop` sends SIGTERM: treat it like Ctrl-C, so we clean up


signal.signal(signal.SIGTERM, on_stop)
(HERE / "nights").mkdir(exist_ok=True)


def now():
    return datetime.datetime.now()


def stamp():
    return now().isoformat(timespec="seconds")


def wake_time():
    if not args.wake:
        return None
    h, m = map(int, args.wake.split(":"))
    t = now().replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > now() else t + datetime.timedelta(days=1)


def my_ip():
    """The Pi's IP, shown on the waiting screen (this replaces the Lab 2 IP screen)."""
    try:
        return subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()[0]
    except Exception:
        return "no network"


def bedtime():
    """The 30-second ritual. Returns the reading the night starts from."""
    flag.set(False)
    button.light(255)
    # Wi-Fi often connects a few seconds after we start, so keep the IP on the screen up to date
    ip = None
    while True:
        if my_ip() != ip:
            ip = my_ip()
            screen.show("Goodnight?", f"Clean the counter, then press the button.   IP {ip}", BLUE)
        if button.wait(timeout=5):
            break
    screen.show("Checking...", "Looking at the counter.", BLUE)
    reading = look(cam.frames(5))
    if total(reading["dishes"]):
        screen.show("Not clean!", f"I see {describe(reading['dishes'])}. "
                    "Clean up and press again, or wait 20 s to start anyway.", RED)
        speak(f"Hmm. I still see {describe(reading['dishes'])}.")
        if button.wait(timeout=20):
            screen.show("Checking...", "Looking again.", BLUE)
            reading = look(cam.frames(5))
    start = describe(reading["dishes"])
    screen.show("Watching", f"Starting with {start}. Goodnight!", GREEN)
    speak("Goodnight. I'm keeping an eye on the counter.")
    button.light(10)                # a dim glow = "I'm on night duty"
    time.sleep(8)
    screen.off()
    return reading


def change(before, after):
    """{"cup": 1} -> {"cup": 2, "bowl": 1} gives "+1 cup, +1 bowl"."""
    parts = []
    for d in sorted(set(before) | set(after)):
        n = after.get(d, 0) - before.get(d, 0)
        if n:
            parts.append(f"{n:+d} {describe({d: abs(n)}).split(' ', 1)[1]}")
    return ", ".join(parts)


def night(log, start):
    """Look every few seconds until the button, --wake or --fake ends the night."""
    snaps = HERE / "snaps"
    snaps.mkdir(exist_ok=True)
    t_start, wake, last, last_beat = time.time(), wake_time(), start, time.time()
    screen_off_at, last_photo = None, time.time()
    print(f"night shift started at {now():%H:%M}"
          + (f", ends at {args.wake}" if wake else "") + ", press the button to end it", flush=True)
    while True:
        # wait for the next look, but keep checking the button
        t_next = time.time() + args.interval
        while time.time() < t_next:
            if screen_off_at and time.time() > screen_off_at:
                screen.off()                   # the proof photo has been up long enough
                screen_off_at = None
            if button.pressed():
                return "button"
            if wake and now() >= wake:
                return "wake time"
            if args.fake and time.time() - t_start > args.fake:
                return "fake night over"
            time.sleep(0.1)
        try:
            frames = cam.frames(3)
            reading = look(frames)
        except Exception as e:
            print("hiccup:", e, flush=True)
            continue
        if reading != last:
            # "reading" in words too, so the class's morning.py can read this log as well
            words = describe(reading["dishes"]) + ("; person at the counter" if reading["person"] else "")
            entry = {"t": stamp(), **reading, "reading": words}
            log.write(json.dumps(entry) + "\n")
            log.flush()
            print(f"{now():%H:%M:%S} {describe(reading['dishes'])}"
                  + (" | person at the counter" if reading["person"] else ""), flush=True)
            if reading["dishes"] != last["dishes"]:
                # proof that the pipeline works: the photo YOLO just looked at, with its boxes,
                # on the screen for PROOF_SECONDS (and saved, unless --no-snaps)
                proof = annotate(frames[0])
                n = total(reading["dishes"])
                screen.photo(proof, f"{now():%H:%M} {change(last['dishes'], reading['dishes'])} "
                                    f"({n} dish{'es' if n != 1 else ''})")
                screen_off_at, last_photo = time.time() + PROOF_SECONDS, time.time()
                if not args.no_snaps:
                    cv2.imwrite(str(snaps / f"{now():%Y%m%d-%H%M%S}.jpg"), proof)
            last = reading
        elif args.check and time.time() - last_photo >= args.check:
            # nothing changed, but show a checkpoint now and then, so you can see it is still working
            n = total(reading["dishes"])
            screen.photo(annotate(frames[0]), f"{now():%H:%M} check: {n} dish{'es' if n != 1 else ''}")
            screen_off_at, last_photo = time.time() + CHECK_SECONDS, time.time()
        if time.time() - last_beat > 600:
            log.write(json.dumps({"t": stamp(), "alive": True}) + "\n")
            log.flush()
            last_beat = time.time()


def morning(path):
    """The reveal: screen, voice and flag."""
    button.light(255)
    screen.show("Good morning", "Let me check the counter...", BLUE)
    entries = [json.loads(line) for line in open(path) if line.strip()]
    facts, text, source = morning_report(entries, args.model, use_qwen=not args.no_qwen)
    print(f"\nmorning report [{source}]:\n{text}\n", flush=True)
    with open(path, "a") as log:
        log.write(json.dumps({"t": stamp(), "event": "report", "text": text, "source": source}) + "\n")
    shame = bool(facts and facts["shame"])
    title = f"SHAME +{total(facts['new'])}" if shame else "All clean!"
    screen.show(title, text, RED if shame else GREEN)
    flag.set(shame)
    speak(text)
    print("press the button to finish (the screen stays on for 30 minutes)", flush=True)
    button.wait(timeout=30 * 60)
    flag.set(False)
    screen.off()
    button.light(0)


try:
    while True:
        start = bedtime()
        path = HERE / "nights" / f"night_{now():%Y%m%d-%H%M}.jsonl"
        with open(path, "w") as log:
            log.write(json.dumps({"t": stamp(), "event": "bedtime", **start}) + "\n")
            why = night(log, start)
            print(f"night over ({why})", flush=True)
            final = look(cam.frames(5))
            log.write(json.dumps({"t": stamp(), "event": "morning", **final}) + "\n")
        shutil.copy(path, HERE / "night_log.jsonl")
        morning(path)
        if args.once or args.source != "0":
            break
except KeyboardInterrupt:
    print("\nstopped")
finally:
    cam.release()
    screen.off()
    button.light(0)
