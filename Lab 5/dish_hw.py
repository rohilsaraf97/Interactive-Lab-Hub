"""
Dish Shame: the hardware. Every part works without its hardware, so the same code runs
on a laptop for testing:

    part          on the Pi                                   without it
    screen        Mini PiTFT (Lab 2)                          prints to the terminal
    button        Qwiic button (Lab 4), or the PiTFT's        press Enter
                  own top button
    button LED    the light inside the Qwiic button           nothing
    flag          servo on the Servo pHAT (Lab 4)             prints "flag up/down"
    voice         Piper (Lab 3) through the speaker           macOS `say`, or prints

    python dish_hw.py      # test every part once and say which ones were found
"""
import atexit
import os
import pathlib
import select
import shutil
import subprocess
import sys
import textwrap
import time

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).parent

# Change these if your wiring is different.
FLAG_CHANNEL = 0        # servo channel on the pHAT
FLAG_DOWN = 10          # degrees: flag hidden
FLAG_UP = 100           # degrees: flag raised (shame!)
VOICE = "en_US-lessac-medium"
VOICES_DIR = HERE / "voices"


class Screen:
    W, H = 240, 135

    def __init__(self):
        self.disp = None
        self._load_fonts()
        # The boot service that shows the IP (piscreen.service, Lab 2) holds the screen's pins
        # ("Device or resource busy"). Pause it while we run, and start it again when we exit.
        if shutil.which("systemctl") and subprocess.run(
                ["systemctl", "is-active", "--quiet", "piscreen.service"]).returncode == 0:
            if subprocess.run(["sudo", "-n", "systemctl", "stop", "piscreen.service"]).returncode == 0:
                atexit.register(subprocess.run, ["sudo", "-n", "systemctl", "start", "piscreen.service"])
                time.sleep(1)
        try:
            self._open()
        except Exception as e:
            print(f"[screen] no Mini PiTFT ({type(e).__name__}: {e}), printing instead")

    def _load_fonts(self):
        try:
            font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            self.fonts = {s: ImageFont.truetype(font, s) for s in (14, 17, 20)}
            self.big = ImageFont.truetype(bold, 34)
        except OSError:                        # no DejaVu (e.g. a Mac): Pillow's own font
            self.fonts = {s: ImageFont.load_default(s) for s in (14, 17, 20)}
            self.big = ImageFont.load_default(34)

    def _open(self):
        """The Mini PiTFT setup from Lab 2's screen_clock.py."""
        import board
        import digitalio
        import adafruit_rgb_display.st7789 as st7789
        disp = st7789.ST7789(
            board.SPI(), cs=digitalio.DigitalInOut(board.D5), dc=digitalio.DigitalInOut(board.D25),
            rst=None, baudrate=64000000, width=135, height=240, x_offset=53, y_offset=40)
        self.backlight = digitalio.DigitalInOut(board.D22)
        self.backlight.switch_to_output()
        self.backlight.value = True
        self.disp = disp

    def _draw(self, img):
        if self.disp:
            self.backlight.value = True        # off() turns it off, so every new picture turns it on
            self.disp.image(img, 90)

    def photo(self, bgr, caption):
        """A camera photo (OpenCV, BGR) scaled to fit, with a caption bar at the bottom."""
        print(f"[screen] photo | {caption}")
        rgb = Image.fromarray(bgr[:, :, ::-1])
        rgb.thumbnail((self.W, self.H))
        img = Image.new("RGB", (self.W, self.H))
        img.paste(rgb, ((self.W - rgb.width) // 2, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((0, self.H - 22, self.W, self.H), fill=(0, 0, 0))
        d.text((4, self.H - 20), caption, font=self.fonts[14], fill=(255, 210, 120))
        self._draw(img)
        return img

    def show(self, title, text="", color=(255, 255, 255), bg=(0, 0, 0)):
        """A big title line and some smaller text under it, wrapped to fit."""
        print(f"[screen] {title} | {text}")
        img = Image.new("RGB", (self.W, self.H), bg)
        d = ImageDraw.Draw(img)
        d.text((6, 2), title, font=self.big, fill=color)
        for size in (20, 17, 14):              # biggest font that still fits
            font = self.fonts[size]
            chars = int(self.W / (size * 0.55))
            lines = textwrap.wrap(text, chars)
            if len(lines) * (size + 3) <= self.H - 44:
                break
        y = 44
        for line in lines:
            d.text((6, y), line, font=font, fill=(230, 230, 230))
            y += size + 3
        self._draw(img)
        return img

    def off(self):
        if self.disp:
            self.disp.image(Image.new("RGB", (self.W, self.H)), 90)
            self.backlight.value = False


class Button:
    """The Qwiic button. Falls back to the PiTFT's top button (GPIO 23), then to Enter."""

    def __init__(self, auto=False):
        self.auto = auto                    # testing: every wait() is "pressed" right away
        self.qwiic = self.gpio = None
        try:
            import qwiic_button
            b = qwiic_button.QwiicButton()
            if b.begin():
                self.qwiic = b
        except Exception:
            pass
        if not self.qwiic:
            try:
                import board
                import digitalio
                self.gpio = digitalio.DigitalInOut(board.D23)
                self.gpio.switch_to_input(pull=digitalio.Pull.UP)
            except Exception:
                pass
        print("[button]", "Qwiic button" if self.qwiic else "PiTFT top button" if self.gpio else
              "no button found, press Enter instead")

    def pressed(self):
        if self.auto:
            return False
        if self.qwiic:
            return self.qwiic.is_button_pressed()
        if self.gpio:
            return not self.gpio.value        # pulled up, so pressed reads False
        if sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.readline()
            return True
        return False

    def wait(self, timeout=None):
        """Wait for a press (and its release). Returns False if the timeout ran out first."""
        if self.auto:
            print("[button] (auto) pressed")
            return True
        t_end = None if timeout is None else time.time() + timeout
        while not self.pressed():
            if t_end and time.time() > t_end:
                return False
            time.sleep(0.05)
        while self.qwiic or self.gpio:
            if not self.pressed():
                break
            time.sleep(0.05)
        return True

    def light(self, brightness):
        """0 = off, 255 = full. Only the Qwiic button has a light."""
        if self.qwiic:
            if brightness:
                self.qwiic.LED_on(brightness)
            else:
                self.qwiic.LED_off()


class Flag:
    """A paper SHAME flag on a servo."""

    def __init__(self):
        self.hat = None
        try:
            import pi_servo_hat
            self.hat = pi_servo_hat.PiServoHat()
            self.hat.restart()
        except Exception as e:
            print(f"[flag] no Servo pHAT ({type(e).__name__}), printing instead")

    def set(self, up):
        print("[flag]", "UP (shame!)" if up else "down")
        if self.hat:
            try:
                self.hat.move_servo_position(FLAG_CHANNEL, FLAG_UP if up else FLAG_DOWN)
            except Exception as e:
                print("[flag] servo error:", e)


def usb_speaker():
    """The Pi's default sound output is HDMI. Find the USB speaker's card instead, e.g. 'plughw:2,0'."""
    try:
        cards = subprocess.run(["aplay", "-l"], capture_output=True, text=True).stdout
        for line in cards.splitlines():
            if line.startswith("card") and "usb" in line.lower():
                return f"plughw:{line.split()[1].rstrip(':')},0"
    except Exception:
        pass
    return None


def speak(text):
    """Say it out loud: Piper on the Pi, `say` on a Mac, otherwise just print it."""
    print(f"[voice] {text}")
    # Quiet mode (e.g. in the library): DISH_QUIET=1, or a file called "quiet" next to this script.
    # `touch quiet` turns the voice off, `rm quiet` turns it back on, no restart needed.
    if os.environ.get("DISH_QUIET") or (HERE / "quiet").exists():
        return
    voice_file = VOICES_DIR / f"{VOICE}.onnx"
    try:
        if voice_file.exists() and shutil.which("aplay"):
            device = usb_speaker()
            piper = subprocess.Popen(
                [sys.executable, "-m", "piper", "--model", VOICE, "--data-dir", str(VOICES_DIR),
                 "--output-raw", "--", text], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            subprocess.run(["aplay", "-q", *(["-D", device] if device else []),
                            "-r", "22050", "-f", "S16_LE", "-t", "raw", "-"],
                           stdin=piper.stdout, check=False)
            piper.wait()
        elif shutil.which("say"):
            subprocess.run(["say", text], check=False)
    except Exception as e:
        print("[voice] could not speak:", e)


if __name__ == "__main__":
    screen, button, flag = Screen(), Button(), Flag()
    screen.show("Hello!", "Testing the screen. Press the button.", color=(120, 200, 255))
    button.light(255)
    print("press the button (or Enter) within 30 s...")
    print("pressed!" if button.wait(timeout=30) else "no press seen")
    button.light(20)
    flag.set(True)
    time.sleep(1.5)
    flag.set(False)
    speak("Dish shame is ready.")
    screen.show("Done", "All parts tested.", color=(120, 255, 120))
