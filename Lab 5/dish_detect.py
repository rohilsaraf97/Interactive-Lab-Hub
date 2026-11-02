"""
Dish Shame: the detector and the interpreter.

YOLO looks at the counter, and interpret_dishes() turns one look into counts:
how many cups, bowls, bottles... and whether a person is standing there.
This is the only thing the rest of the system (and Qwen) ever knows about the night.

    python dish_detect.py                    # look once with the webcam and print the counts
    python dish_detect.py --source pic.jpg   # look at a photo instead
"""
import argparse
import collections
import pathlib

import cv2
from ultralytics import YOLO

# The COCO classes that count as "dishes". Everything else YOLO sees is ignored.
DISHES = ["cup", "bowl", "wine glass", "bottle", "fork", "knife", "spoon"]
PLURAL = {"cup": "cups", "bowl": "bowls", "wine glass": "wine glasses", "bottle": "bottles",
          "fork": "forks", "knife": "knives", "spoon": "spoons"}

HERE = pathlib.Path(__file__).parent
_model = None


def load_model():
    """The NCNN export runs fastest on the Pi; fall back to the .pt weights if it isn't there."""
    global _model
    if _model is None:
        ncnn = HERE / "yolo26n_ncnn_model"
        _model = YOLO(str(ncnn), task="detect") if ncnn.exists() else YOLO("yolo26n.pt")
    return _model


def interpret_dishes(r):
    """Turn one YOLO result into {"dishes": {"cup": 2, ...}, "person": True/False}."""
    model = load_model()
    names = [model.names[int(c)] for c in r.boxes.cls]
    counts = collections.Counter(n for n in names if n in DISHES)
    return {"dishes": dict(sorted(counts.items())), "person": "person" in names}


def look(frames, conf=0.35):
    """Look at a few frames and keep the median count per dish.

    One frame alone flickers (a cup is there, then it isn't), so we take the middle value.
    """
    model = load_model()
    keep = [k for k, v in model.names.items() if v in DISHES or v == "person"]
    readings = [interpret_dishes(model.predict(f, conf=conf, classes=keep, verbose=False)[0])
                for f in frames]
    out = {}
    for d in DISHES:
        vals = sorted(rd["dishes"].get(d, 0) for rd in readings)
        if vals[len(vals) // 2]:
            out[d] = vals[len(vals) // 2]
    person = sum(rd["person"] for rd in readings) > len(readings) / 2
    return {"dishes": out, "person": person}


def annotate(frame, conf=0.35):
    """The frame with a box and a label around every dish (and person) YOLO finds.

    Drawn with OpenCV, not ultralytics' r.plot(): plot() wants to download a font,
    and the night runs without internet.
    """
    model = load_model()
    keep = [k for k, v in model.names.items() if v in DISHES or v == "person"]
    r = model.predict(frame, conf=conf, classes=keep, verbose=False)[0]
    img = frame.copy()
    for box in r.boxes:
        name = model.names[int(box.cls)]
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        color = (255, 200, 120) if name == "person" else (0, 165, 255)     # BGR: blue-ish / orange
        # thick lines and big text: the photo gets shrunk to 240 px wide for the Mini PiTFT
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 5)
        label = f"{name} {float(box.conf):.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1.1, 3)
        cv2.rectangle(img, (x1, max(0, y1 - th - 12)), (x1 + tw + 8, y1), color, -1)
        cv2.putText(img, label, (x1 + 4, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 3)
    return img


def total(dishes):
    return sum(dishes.values())


def describe(dishes):
    """{"cup": 2, "bowl": 1} -> "2 cups, 1 bowl"."""
    if not dishes:
        return "no dishes"
    return ", ".join(f"{n} {d if n == 1 else PLURAL[d]}" for d, n in dishes.items())


class Camera:
    """The webcam, or a photo / a folder of photos (handy for testing on a laptop)."""

    def __init__(self, source="0"):
        self.photos = None
        if source.isdigit():
            self.cap = cv2.VideoCapture(int(source))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if not self.cap.isOpened():
                raise SystemExit("no webcam found: is it plugged in?")
        else:
            p = pathlib.Path(source)
            if not p.exists():
                raise SystemExit(f"{source} does not exist")
            self.photos = sorted(p.glob("*.jpg")) + sorted(p.glob("*.png")) if p.is_dir() else [p]
            if not self.photos:
                raise SystemExit(f"no photos in {source}")
            self.i = 0

    def frames(self, n=3):
        """n fresh frames from the webcam, or the next photo (repeated n times)."""
        if self.photos is not None:
            img = cv2.imread(str(self.photos[min(self.i, len(self.photos) - 1)]))
            self.i += 1
            return [img] * n
        for _ in range(4):             # the webcam buffers a few frames; skip the stale ones
            self.cap.grab()
        out = []
        for _ in range(n):
            ok, f = self.cap.read()
            if ok:
                out.append(f)
        if not out:
            raise RuntimeError("no frame from the webcam")
        return out

    def release(self):
        if self.photos is None:
            self.cap.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="0", help="webcam number, a photo, or a folder of photos")
    args = parser.parse_args()
    cam = Camera(args.source)
    frames = cam.frames()
    reading = look(frames)
    print(describe(reading["dishes"]), "| person at the counter" if reading["person"] else "")
    cv2.imwrite("look.jpg", frames[0])
    print("saved what the camera saw to look.jpg")
    cam.release()
