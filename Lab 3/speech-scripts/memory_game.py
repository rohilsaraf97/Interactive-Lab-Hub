#!/usr/bin/env python3
"""Voice memory game ("I packed my suitcase"): you vs. the Pi. Audio only, no LLM.

The Pi says a word. You repeat everything and add ONE new word (any word, not one
already used). Then the Pi repeats everything and adds its own. Survive 10 rounds.

Say "wrong" or press the Qwiic button (any time, even mid-sentence) to call out the
Pi when it slips up on purpose, or when it mishears you. LED: pulsing = Pi speaking,
solid = your turn, off = thinking.

    python memory_game.py
"""

import difflib
import queue
import random
import re
import signal
import sys
import time
from pathlib import Path

import numpy as np
import sherpa_onnx
import sounddevice as sd
from faster_whisper import WhisperModel
from piper import PiperVoice

try:                       # lets us slow the voice down (piper 1.3+)
    from piper import SynthesisConfig
except ImportError:
    SynthesisConfig = None

# ------------------------------------------------------------------- settings
LAB_DIR = Path(__file__).resolve().parent.parent
VAD_MODEL = LAB_DIR / "models" / "silero_vad.onnx"
VOICE = LAB_DIR / "voices" / "en_US-lessac-medium.onnx"
WHISPER_MODEL = "base.en"

RATE = 16000
WIN_ROUNDS = 10        # rounds to survive
CALLOUTS = 3           # call-outs per game
MISTAKE_RATE = 0.3     # chance per Pi turn that it slips up on purpose (max 2 a game)
CALLOUT_WINDOW = 4.0   # seconds to call out a wrong read-back
CONFIRM_WINDOW = 2.0   # seconds to call out your new word when all looked fine
EXTRA_WAIT = 2.5       # patience if you pause before your new word
VAD_SILENCE = 0.5      # silence that ends your turn
VAD_THRESHOLD = 0.5    # higher ignores more noise, may clip your first word
ECHO_TAIL = 0.2        # the mic ignores this long after the Pi stops talking
SLOWNESS = 1.2         # the Pi's voice: 1.0 = normal, higher = slower
WORD_GAP = 0.6         # seconds of silence between the words of a sequence

POOL = ("apple chair bicycle lamp window river pencil candle garden bridge mirror cloud "
        "basket ladder guitar orange pillow bottle tiger camera pizza rocket penguin "
        "blanket umbrella banana castle dragon hammer island jacket kettle lemon magnet "
        "noodle ocean piano quilt rabbit spoon turtle violin wallet zebra cactus donut "
        "engine feather glacier helmet igloo jungle kitten lantern mountain needle parrot "
        "rainbow sandwich tractor").split()
SKIP = {"and", "the", "then", "um", "uh", "a", "an"}
HALLUCINATIONS = {"thank you", "thanks for watching", "you", "bye", "thanks"}
FILLER = set("the a an word it its was is i said say my last that number um uh no not and "
             "so sorry wait meant actually wrong challenge okay ok yes yeah one me you got "
             "get should be of nope nah incorrect callout call out right hmm well first "
             "second third fourth fifth sixth seventh eighth ninth tenth".split())

known = []             # words in this game: near-misses ("lamb") snap to these
voice = whisper = vad = q = btn = mic = None
cache, sr, window, spoke_end = {}, 22050, 512, 0.0


# ----------------------------------------------------------------- text logic
def log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def tokens(text):
    return re.findall(r"[a-z]+", text.lower())


def snap(word):
    near = difflib.get_close_matches(word, known, n=1, cutoff=0.75)
    return word if word in known or not near else near[0]


def parse(text):
    return [snap(t) for t in tokens(text) if t not in SKIP]


def content(text):
    """The real words in a correction, minus 'wrong', 'the', 'I said', 'last'..."""
    return [snap(t) for t in tokens(text) if t not in FILLER]


def is_callout(text):
    toks = tokens(text)
    said = " ".join(toks)
    return bool({"no", "nope", "nah"} & set(toks) or "call out" in said or "not right" in said
                or any(difflib.get_close_matches(t, ["wrong", "challenge", "incorrect"],
                                                 n=1, cutoff=0.8) for t in toks))


def left(n):
    return "No call-outs left." if n <= 0 else f"{n} call-out{'' if n == 1 else 's'} left."


# ------------------------------------------------------- button + LED (Qwiic)
def led(mode):
    """on = solid, pulse = blinking, breathe = slow fade, anything else = off."""
    try:
        if mode == "on":
            btn.LED_on(255)
        elif mode == "pulse":
            btn.LED_config(255, 600, 300, 1)
        elif mode == "breathe":
            btn.LED_config(255, 2000, 400, 25)
        else:
            btn.LED_off()
    except Exception:
        pass   # no button: voice-only


def pressed():
    try:
        return bool(btn.has_button_been_clicked())
    except Exception:
        return False


def clear():
    try:
        btn.clear_event_bits()
    except Exception:
        pass


def wait_for_press():
    led("breathe")
    clear()
    while not pressed():
        time.sleep(0.05)
    clear()
    led("off")


# ------------------------------------------------------------------- speaking
def render(text):
    global sr
    if text not in cache:
        parts = []
        slow = SynthesisConfig(length_scale=SLOWNESS) if SynthesisConfig else None
        for chunk in voice.synthesize(text, syn_config=slow) if slow else voice.synthesize(text):
            parts.append(np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16))
            sr = chunk.sample_rate
        cache[text] = np.concatenate(parts)
    return cache[text]


def play_audio(audio, rate, can_interrupt=False):
    """Play audio. Returns True if the button cut the Pi off mid-sentence."""
    global spoke_end
    led("pulse")
    sd.play(audio, samplerate=rate)
    cut = False
    if can_interrupt and btn:
        end = time.perf_counter() + len(audio) / rate
        while time.perf_counter() < end and not cut:
            cut = pressed()
            time.sleep(0.03)
        if cut:
            sd.stop()
    sd.wait()
    spoke_end = time.perf_counter()
    return cut


def say(text, can_interrupt=False):
    log("PI", text)
    return play_audio(render(text), sr, can_interrupt)


def say_words(words, lead="", can_interrupt=False):
    """A whole sequence as one audio buffer, so there are no gaps from synthesis."""
    log("PI", f"{lead} {', '.join(words)}".strip())
    parts = [render(lead)] if lead else []
    for w in words:
        parts += [render(w), np.zeros(int(WORD_GAP * sr), dtype=np.int16)]
    return play_audio(np.concatenate(parts), sr, can_interrupt)


def beep():
    """'Go ahead' tone: the mic is open."""
    t = np.linspace(0, 0.12, int(0.12 * RATE), endpoint=False)
    play_audio((0.3 * np.sin(2 * np.pi * 880 * t) * 32767).astype(np.int16), RATE)


# ------------------------------------------------------------------ listening
def listen(timeout=None, flush=True, stop=None):
    """One utterance of speech, or None on timeout / stop().

    flush=True drops what the mic heard while the Pi was talking (keeps what you
    said after it stopped). flush=False keeps going, e.g. for a late new word.
    """
    todo = []
    if flush:
        while not q.empty():
            t, chunk = q.get_nowait()
            if t >= spoke_end + ECHO_TAIL:
                todo.append(chunk)
        vad.reset()
    buf = np.empty(0, dtype=np.float32)
    t0, talking_since = time.perf_counter(), None
    while True:
        now = time.perf_counter()
        if vad.is_speech_detected():
            talking_since = talking_since or now
            if now - talking_since > 10:     # steady noise: don't record forever
                vad.flush()
                talking_since = None
        else:
            talking_since = None
            if (timeout and now - t0 > timeout) or (stop and stop()):
                return None
        try:
            chunk = todo.pop(0) if todo else q.get(timeout=0.05)[1]
        except queue.Empty:
            chunk = None
        if chunk is not None:
            buf = np.concatenate([buf, chunk])
            while len(buf) >= window:
                vad.accept_waveform(buf[:window])
                buf = buf[window:]
        if not vad.empty():
            utt = np.array(vad.front.samples, dtype=np.float32)
            vad.pop()
            if len(utt) > 0.3 * RATE and np.sqrt(np.mean(utt ** 2)) > 0.01:
                return utt   # (shorter or quieter than that: a click or a cough)


def transcribe(utt):
    pad = np.zeros(int(0.4 * RATE), dtype=np.float32)   # abrupt first words get dropped
    segments, _ = whisper.transcribe(
        np.concatenate([pad, utt, pad]), beam_size=1, language="en", temperature=0.0,
        without_timestamps=True, condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()


# ----------------------------------------------------------------------- game
def play_game():
    """The whole game as a state machine: each `state` below ends by choosing the next."""
    known.clear()
    sequence, heard = [], []
    callouts, rounds, caught, slips = CALLOUTS, 0, 0, 0
    slip = None                 # (position, wrong word, true word) while the Pi has slipped
    utt = fix = why = None      # your audio / call-out speech holding a fix / why you lost
    silent, state = False, "pi_turn"

    def problem():
        """None if your turn is valid, else (what the Pi says, why you'd lose)."""
        n = len(sequence)
        if heard[:n] == sequence and len(heard) == n:
            return "I heard the sequence, but no new word.", "You forgot to add a new word."
        if heard[:n] == sequence and len(heard) > n + 1:
            return f"I heard {len(heard) - n} new words. Only add one.", "You added more than one new word."
        if len(heard) != n + 1 or heard[:n] != sequence:
            return "I heard: " + ", ".join(heard) + ".", "That doesn't match."
        if heard[-1] in sequence:
            return f"{heard[-1]} is already in the sequence.", f"{heard[-1]} was already used."

    while state not in ("win", "lose"):
        log("STATE", state)

        if state == "pi_turn":                       # the Pi repeats everything + adds a word
            clear()
            sequence.append(random.choice([w for w in POOL if w not in sequence] or POOL))
            known[:] = sequence
            spoken, slip, silent = list(sequence), None, False
            if len(spoken) >= 3 and slips < 2 and random.random() < MISTAKE_RATE:
                pos = random.randrange(len(spoken) - 1)   # an OLD word you already heard, never
                                                          # its brand-new one (you can't know that)
                slip = (pos, random.choice([w for w in POOL if w not in sequence]), spoken[pos])
                spoken[pos], slips = slip[1], slips + 1
            cut = say_words(spoken, "I'll start." if len(spoken) == 1 else f"Round {rounds + 1}.", True)
            state = ("caught" if slip else "false_alarm") if cut else "listen"

        elif state == "listen":                      # your turn: beep, solid LED
            led("on")
            beep()
            utt = listen(timeout=12, stop=pressed)
            if pressed():
                state = "caught" if slip else "false_alarm"
            elif utt is not None:
                state = "process"
            elif silent:
                state, why = "lose", "Time's up."
            else:
                silent = True
                say("I didn't hear you. Try again.")

        elif state == "caught":                      # you called out a real Pi slip-up
            clear()
            _, bad, true = slip
            slip, caught = None, caught + 1
            say(f"Busted! I said {bad}, but it was {true}. Nice ears.")
            say_words(sequence, "Here it is again.")
            state = "listen"

        elif state == "false_alarm":                 # you called out, but the Pi was right
            clear()
            callouts -= 1
            if callouts < 0:
                state, why = "lose", "You're out of call-outs."
            else:
                say(f"Nope, I got that one right. {left(callouts)} Listen again.")
                say_words(sequence, "Again.")
                state = "listen"

        elif state == "process":                     # thinking: LED off
            led("off")
            t0 = time.perf_counter()
            raw = transcribe(utt)
            heard = parse(raw)
            log("HEARD", f"{raw!r} -> {' '.join(heard)} ({time.perf_counter() - t0:.1f}s)")
            if slip and is_callout(raw):
                state = "caught"
                continue
            if not heard or " ".join(tokens(raw)) in HALLUCINATIONS:
                state = "listen"
                continue
            for _ in range(2):                       # paused before your new word? wait
                if len(heard) > len(sequence):
                    break
                led("on")
                more = listen(timeout=EXTRA_WAIT, flush=False)
                if more is None:
                    break
                led("off")
                heard += parse(transcribe(more))
            if slip:                                 # repeated the Pi's slip-up: you fell for it
                faulty = list(sequence)
                faulty[slip[0]] = slip[1]
                if heard[:len(faulty)] == faulty:
                    state, why = "lose", f"Gotcha! I said {slip[1]}, but it was {slip[2]}."
                    continue
            state = "readback"

        elif state == "readback":                    # the Pi says what it heard
            bad = problem()
            if bad is None:
                if slip:                             # you repeated the TRUE sequence
                    slip, caught = None, caught + 1
                    say("Ha, I slipped up and you didn't fall for it.")
                say(f"You added {heard[-1]}.", True)
            else:
                say(bad[0] + (" Say wrong or press the button" if btn else " Say wrong")
                    + " if I got it wrong.", True)
            state = "wait"

        elif state == "wait":                        # your chance to call out the machine
            led("on")
            fix = None
            u = listen(timeout=CONFIRM_WINDOW if not problem() else CALLOUT_WINDOW, stop=pressed)
            called = pressed()
            if u is not None and not called:
                led("off")
                text = transcribe(u)
                log("USER", text)
                # "wrong", or just saying the whole sequence again, counts as a call-out
                called = is_callout(text) or (problem() and len(content(text)) >= 2)
                fix = text
            if called:
                state = "challenge"
            elif problem():
                state, why = "lose", problem()[1]
            else:
                state = "next"

        elif state == "challenge":                   # a call-out costs one of your 3
            clear()
            if callouts <= 0:
                state, why = "lose", "You're out of call-outs."
                continue
            callouts -= 1
            n = len(sequence)
            redo = len(heard) != n + 1 or sum(a != b for a, b in zip(heard, sequence)) > 1
            if not (fix and content(fix)):           # no fix given yet: ask for it
                fix = None
                led("on")
                say("Okay. Say the whole sequence again, with your new word." if redo
                    else "Okay, what did I get wrong?")
            state = "correct"

        elif state == "correct":                     # replace the misheard word
            if fix is None:
                led("on")
                u = listen(timeout=8)
                led("off")
                fix = transcribe(u) if u is not None else ""
                log("USER", fix)
            words, fix, word = content(fix), None, None
            if len(words) >= 2:                      # you said the whole sequence again
                heard = words
            elif words:                              # "last word, lamp": swap that one in
                word = words[0]
                wrong = [i for i in range(min(len(sequence), len(heard))) if heard[i] != sequence[i]]
                i = next((i for i in wrong if sequence[i] == word), wrong[0] if wrong else len(heard) - 1)
                heard[i] = word
            else:
                state, why = "lose", "I couldn't understand the correction."
                continue
            bad = problem()
            if bad is None:
                say(f"Got it. {word + '. ' if word else ''}{left(callouts)} Let's continue.")
                state = "next"
            else:
                say("Even with that fix, that doesn't work.")
                state, why = "lose", bad[1]

        elif state == "next":                        # round passed: your word joins the game
            rounds, sequence = rounds + 1, list(heard)
            log("GAME", f"round {rounds}/{WIN_ROUNDS}: {', '.join(sequence)}")
            state = "win" if rounds >= WIN_ROUNDS else "pi_turn"

    if state == "win":
        say(f"You win! {rounds} rounds, and you caught me {caught} times. Absolute legend.")
    else:
        say(f"{why} Game over. You passed {rounds} of {WIN_ROUNDS} rounds. "
            f"The sequence was: {', '.join(sequence)}.")
    led("off")


def main():
    global voice, whisper, vad, q, btn, mic, window
    for path, what in [(VAD_MODEL, "VAD model"), (VOICE, "Piper voice")]:
        if not path.is_file():
            sys.exit(f"{what} not found at {path}. Run ./setup.sh first.")

    print("Loading...", flush=True)
    try:
        import qwiic_button
        btn = qwiic_button.QwiicButton()
        if not btn.begin():
            raise RuntimeError("not found on I2C")
        clear()
    except Exception as e:
        btn = None
        log("BUTTON", f"no Qwiic button ({e}); voice-only")
    voice = PiperVoice.load(str(VOICE))
    whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=4)
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(VAD_MODEL)
    cfg.silero_vad.min_silence_duration = VAD_SILENCE
    cfg.silero_vad.threshold = VAD_THRESHOLD
    cfg.silero_vad.min_speech_duration = 0.25
    cfg.sample_rate = RATE
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=30)
    window = cfg.silero_vad.window_size
    q = queue.Queue()
    mic = sd.InputStream(channels=1, dtype="float32", samplerate=RATE, blocksize=RATE // 20,
                         callback=lambda data, *_: q.put((time.perf_counter(), data[:, 0].copy())))
    mic.start()   # `mic` must stay referenced, or Python frees the stream while it runs

    for phrase in ["I'll start.", "Again.", "Here it is again.", "I didn't hear you. Try again.",
                   "Okay, what did I get wrong?"] + [f"Round {i}." for i in range(2, WIN_ROUNDS + 1)]:
        render(phrase)
    transcribe(np.zeros(RATE, dtype=np.float32))     # warm Whisper up

    rules = ("Memory game! I say a word. You repeat everything and add one new word. "
             "Then I do the same. If I slip up, or if I mishear you, say wrong")
    if btn:
        say(rules + " or press the button. Press the button to start.")
        wait_for_press()
    else:
        say(rules + ". Here we go.")
    while True:
        play_game()
        if not btn:
            break
        say("Press the button to play again.")
        wait_for_press()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # `kill` / systemd stop
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:                  # runs on Ctrl-C, kill, a crash, or a normal exit
        led("off")
        sd.stop()
        if mic:
            mic.close()