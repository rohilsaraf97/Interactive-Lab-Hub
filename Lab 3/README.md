# Chatterboxes

**Rohil Saraf, Andreas Kilbinger**

[![Watch the video](https://user-images.githubusercontent.com/1128669/135009222-111fe522-e6ba-46ad-b6dc-d1633d21129c.png)](https://www.youtube.com/embed/Q8FWzLMobx0?start=19)

In this lab, we want you to design interaction with a speech-enabled device — something that listens and talks to you. This device can do anything *but* control lights (since we already did that in Lab 1). First, we want you to storyboard what you imagine the conversational interaction to be like. Then you will use wizarding techniques to elicit examples of what people might say, ask, or respond. We then want you to use the examples collected from at least two other people to inform the redesign of the device.

We will focus on **audio** as the main modality for interaction to start; these general techniques can be extended to **video**, **haptics** or other interactive mechanisms in the second part of the Lab.

A note on what you are building with. Speech interfaces are usually taught as two boxes — speech-in, speech-out — and that framing hides the part that actually determines whether an interaction works. Between listening and speaking sits the question of **whose turn it is**: when does the device decide you have finished talking, and how long does it make you wait before it answers? This lab gives you direct control over both, and we will ask you to notice what changes when you move them.

## Prep for Part 1: Get the Latest Content and Pick up Additional Parts

Please check instructions in [prep.md](prep.md) and complete the setup.

### Pick up Web Camera If You Don't Have One

Students who have not already received a web camera will receive their Webcam and at the beginning of lab. If you cannot make it to class this week, please contact the TAs to ensure you get these.

### Get the Latest Content

As always, pull updates from the class Interactive-Lab-Hub to both your Pi and your own GitHub repo.

**\[recommended\]** Option 1: On the Pi, `cd` to your `Interactive-Lab-Hub`, pull the updates from upstream (class lab-hub) and push the updates back to your own GitHub repo. You will need the *personal access token* for this.

```
pi@ixe00:~$ cd Interactive-Lab-Hub
pi@ixe00:~/Interactive-Lab-Hub $ git pull upstream Fall2026
pi@ixe00:~/Interactive-Lab-Hub $ git add .
pi@ixe00:~/Interactive-Lab-Hub $ git commit -m "get lab3 updates"
pi@ixe00:~/Interactive-Lab-Hub $ git push
```

Option 2: On your own GitHub repo, create a pull request to get updates from the class Interactive-Lab-Hub. After you have the latest updates online, go to your Pi, `cd` to your `Interactive-Lab-Hub` and use `git pull`.

---

# Part 1

## Setup

Create and activate a virtual environment for this lab:

```
pi@ixe00:~$ cd Interactive-Lab-Hub/Lab\ 3
pi@ixe00:~/Interactive-Lab-Hub/Lab 3 $ python3 -m venv .venv
pi@ixe00:~/Interactive-Lab-Hub/Lab 3 $ source .venv/bin/activate
(.venv) pi@ixe00:~/Interactive-Lab-Hub/Lab 3 $
```

Install the Python dependencies:

```
(.venv) $ pip install -r requirements.txt
```

This takes a few minutes. If you would like it to take considerably less time, [`uv`](https://docs.astral.sh/uv/) is a drop-in replacement for `pip` that is dramatically faster on the Pi:

```
(.venv) $ pip install uv && uv pip install -r requirements.txt
```

Then run the setup script, which installs the classic speech synthesizers, downloads the voice activity detection model, and pre-fetches a neural voice and a speech recognition model so you are not waiting on downloads during lab:

```
(.venv):~$ cd speech-scripts
(.venv) $ ./setup.sh
```

Check your audio devices before going further. `arecord -l` lists capture devices and `aplay -l` lists playback devices; if your webcam microphone or Bluetooth speaker does not appear, fix that first — every script below assumes the system defaults are the ones you want.

## A. Text to Speech

Your Pi can speak in several quite different ways, and the differences are audible in a way that matters for design. In `speech-scripts/` there are shell scripts for each.

### The classic engines

```
(.venv) $ cd speech-scripts

(.venv) $ sudo apt update
(.venv) $ sudo apt install -y espeak festival festvox-kallpc16k

(.venv) $ ./espeak_demo.sh
(.venv) $ ./festival_demo.sh
```

You can run these `.sh` files by typing `./filename`, and read one with `cat filename`. You can also play audio files directly with `aplay filename` — try `aplay lookdave.wav`.

These are all decades-old technology and they sound like it. `espeak-ng` is a *formant synthesizer*: it generates speech from an acoustic model of the vocal tract, which is why it sounds robotic but also why the whole thing fits in a couple of megabytes and responds instantly. `festival` is *concatenative*: they stitch together recorded fragments of a real speaker, which sounds more human but breaks audibly at the seams.

### Neural TTS with Piper

Note that the Piper command line changed in version 1.x — voices are now downloaded explicitly with `python3 -m piper.download_voices`, and you invoke it as `python3 -m piper`. Tutorials you find online may show the old `echo ... | piper --model ...` form, which no longer works. Browse the [voice samples](https://rhasspy.github.io/piper-samples) and download a different one if you'd like:

```
(.venv) $ python3 -m piper.download_voices en_US-lessac-medium
```

[Piper](https://github.com/OHF-Voice/piper1-gpl) synthesizes speech with a small neural network, runs comfortably on the Pi 5, and sounds markedly better than the above.

```
(.venv) $ ./piper_demo.sh
```

The demo script also shows `--output-raw`, which streams audio to the speaker as it is generated rather than writing a file first. Listen for the difference in how quickly speech begins. In a conversational system this gap is the thing your user experiences as responsiveness.

\*\***Write your own shell file to use your favorite of these TTS engines to have your Pi greet you by name.**\*\*
(This shell file should be saved to your own repo for this lab.)
File saved.

\*\***Then answer: Is the same greeting, in these different voices, the same greeting? Describe one concrete way the voice changed what the utterance seemed to mean or who seemed to be speaking.**\*\*

## B. Speech to Text

We use [faster-whisper](https://github.com/SYSTRAN/faster-whisper), a reimplementation of OpenAI's Whisper model that runs several times faster on CPU and does not require PyTorch. All processing happens on the Pi; nothing is sent to a server.

```
(.venv) $ python transcribe.py lookdave.wav
```

The transcript is not the interesting output here — the timings are. Run it again with a larger model and compare:

```
(.venv) $ python transcribe.py lookdave.wav --model base.en
(.venv) $ python transcribe.py lookdave.wav --model small.en
#  noted that the first run may take longer because the model is downloaded, and that the HF unauthenticated-request warning is expected and not an error.
```

Available sizes, smallest first: `tiny.en`, `base.en`, `small.en`, `medium.en`. The `.en` variants are English-only and faster than their multilingual counterparts at the same size.

\*\***Record a few seconds of your own speech (`arecord -d 5 -f cd -c 1 -r 16000 test.wav`) and transcribe it with at least two model sizes. Report the real-time factor for each. At what point does the accuracy improvement stop being worth the delay, for a system that has to answer you?**\*\*
The tiny model actually worked alright for most use cases. The small, tiny and base models all had shorter model load times so the performance diff was not very apparent. However, the medium model took a long time to load didn't offer any significant performance improvements. The medium and small models performed better when it came to transcribing proper nouns such as names. But for common language, I would value response times more to make the system feel more snappy.

\*\***Write your own script that verbally asks for a numerical input (a phone number, zipcode, number of pets) and records the answer the respondent provides.**\*\* Numbers are a good stress test — transcription systems make characteristic errors on digit strings, and you will want to know what they are before you design around them.
Added a script which records my NetID

## C. Turn-taking: knowing when someone has stopped talking

Everything so far has worked on fixed audio files. A real conversational device does not get told when to start and stop recording — it has to decide. This is the problem that makes speech interfaces hard, and it is mostly not a speech recognition problem.

We use a **voice activity detector** (VAD) to segment the microphone stream into utterances. `listen.py` runs Silero VAD continuously and hands each detected utterance to faster-whisper:

```
(.venv) $ cd speech-scripts
(.venv) $ python listen.py
```

Speak, pause, and watch it transcribe. Now change the endpointing threshold, the amount of silence the system requires before it decides your turn is over:

```
(.venv) $ python listen.py --min-silence 0.2
(.venv) $ python listen.py --min-silence 1.5
```

\*\***Try both extremes, and something in between. Describe what each one feels like to talk to. Note specifically: at 0.2s, what kinds of normal speech get cut off? At 1.5s, what does the delay make the system seem like?**\*\*

There is no correct value. A system that takes drink orders and a system that listens to someone think out loud want very different thresholds, and the right one depends on what your users are doing with their pauses.

When the minimum silence is small (0.2 s), the system cuts me off too soon. It treats any short pause as the end of my turn, even when I'm just thinking, coming up with the next word, or saying filler words like "um." A single sentence ends up split into several pieces, and each piece gets transcribed on its own. With a long threshold like 1.5 s, it never interrupts me, but there is a significant wait after I finish my sentence, and the system feels laggy. Because transcription time gets added on top of the wait, I couldn't tell whether it had heard me, and I was tempted to repeat myself.

We settled on 0.5 s, which is a good middle ground for most speech. It's still not perfect for our memory game, because players often pause before adding their new word. To handle that, the game keeps listening for an extra 2.5 s whenever the list isn't complete yet. We also added a beep and a solid LED when the mic opens, so the player knows when it's their turn to talk instead of guessing from the silence.

### The complete loop

`echo_bot.py` puts the pieces together: it listens, endpoints, transcribes, and speaks a reply through Piper. The dialogue policy is deliberately trivial — it repeats what you said — so that everything you notice is a property of the timing rather than the content.

```
(.venv) $ python echo_bot.py
```

## D. Storyboard

We are building a memory game between me and the device. It says a word, I repeat it and add a new one, it repeats the whole list and adds another, and so on, the list keeps growing until one of us messes up.

**Dialogue script, with pauses:**

| Who | Line | Wait |
|---|---|---|
| Device | "Let's play. First word: apple." | |
| Device | "Your turn." | listens, 2s silence |
| Me | "Apple, chair" | |
| Device | "Apple, chair, lamp." | |
| Device | "Your turn." | listens, 2.5s silence |
| Me | "Apple, chair, lamp, sofa" | |
| Device | "Apple, chair, lamp, sofa, window." | |
| Device | "Your turn." | listens, 3s silence (longer list = more recall time) |
| ... | (continues, +0.5s silence per round) | |
| Device (on my miss) | "That's a miss, it was window, not curtain. We made it to 5 words." | 1s |

<img width="5712" height="4284" alt="IMG_8566" src="https://github.com/user-attachments/assets/ee541ae6-a681-4578-970b-716f162ef5a8" />


## E. Acting out the dialogue

Find a partner, and *without sharing the script with your partner* try out the dialogue you've designed, where you (as the device designer) act as the device you are designing. Please record this interaction (for example, using Zoom's record feature).

\*\***Describe if the dialogue seemed different than what you imagined when it was acted out, and how.**\*\*

The dialogue during the trial went fairly much as we expected. The difference was the lag. When I paused to simulate the device's processing delay, it wasn't what my subject expected. He seemed confused and felt like he had done something wrong. The subject was also unsure about the device repeating the whole sequence, since that is not standard in the gameplay of this game.

https://youtu.be/xjf7KC0qnVY

We gave feedback to these teams:
Max Corkrans Coffee Order device
Max's coffee machine device worked great and recorded my order too. I did have to rely on the screen to confirm my order and what the machine had heard, and it did get it wrong sometimes. Adding the screen, the repetitions, and the ability to go back and start over definitely helped, and it made for a full audio and visual experience with more than just voice to rely on.

Viktor's team: https://github.com/LaboriouslyExquisite/Interactive-Lab-Hub/blob/Fall2026/Lab%203/README.md
Great idea! In fact, it would have been really useful for recording these demos. Does this mean the device is always listening? Is there an indication of when it is? Also, in the final video, is the device's audio instruction recorded too? This is amazing though! I could see it being used for hands-free recording of tutorials, cooking videos, or lectures.

Gabriela's team: https://github.com/cgyh98/Interactive-Lab-Hub/tree/Fall2026/Lab%203
I like that you switched from the fridge to the plant. A plant that asks for things is more useful, and it's the opposite of a typical assistant. Writing the dialogue out was a good move, because it exposed that the plant only has a light sensor and can't know which way to turn. One idea is to lean into that. Instead of one command, the plant could react as the user turns the pot ("warmer," "better," "worse"), so the guessing game becomes an interaction. It also tells the user the plant is paying attention. On timing, I agree that 0.4 s is too short when people are doing something physical between lines. You could use a longer pause, or have the plant wait until it senses the light has stopped changing before it listens.

We got feedback from the above teams as well
Team 1: The system checks the box of being interactive, and it uses STT and TTS well. Using a person's verbal response to test whether they truly memorized words is interesting, since similar online games test visual memory and this one tests verbal memory. It could be fun on a road trip to keep people engaged with each other. A local multiplayer mode would be a great addition.

Team 2: So awesome. It feels intuitive, like there is a language model running behind it. However, the pauses are too long, and it's easy to mislead it by saying "wrong" even when it wasn't wrong.

Team 3: I wasn't sure when to press the button, or when to start speaking. Sometimes my first words might get cut off.

---

# Lab 3 Part 2

For Part 2, you will redesign the interaction with the speech-enabled device using the data collected, as well as feedback from part 1.

## Prep for Part 2

1. What are concrete things that could use improvement in the design of your device? For example: wording, timing, anticipation of misunderstandings.

Misunderstandings: Speech recognition sometimes hears the wrong word. We added a call-out: say "wrong" or press the button, then say the correct word, and the Pi swaps it in and continues. Players get 3 call-outs per game.
Wording: "Your turn." was slow and easy to talk over, so we replaced it with a beep and a solid LED. We also made the error messages specific, like "You forgot to add a new word."
Timing: A fixed silence cut players off when they paused before their new word. The turn now ends after 0.5 s of silence, and the Pi listens up to 2.5 s more if the list is incomplete.
Goal: The game now ends with a win after 10 rounds, and the Pi occasionally slips up on purpose for the player to catch.

2. What are other modes of interaction *beyond speech* that you might also use to clarify how to interact? In particular: how does someone know when the device is listening, and when it is thinking? You have a screen and an LED.

The player can't see a screen in this game, so we use the LED and sound to show what the device is doing:

Solid LED plus a beep: it's listening to you.
Pulsing LED: it's speaking.
LED off: it's thinking.

3. Make a new storyboard, diagram and/or script based on these reflections.

<img width="5712" height="4284" alt="IMG_8624" src="https://github.com/user-attachments/assets/b3b289e6-1399-4473-806c-382d524b6405" />

Device: "Memory game! ... Press the button to start."
Me: (presses the button)
Device: "I'll start. Banana." (beep, LED solid)
Me: "Banana, laptop."
Device: "You added laptop." (2 s to call out)
Device: "Round 2. Banana, laptop, zebra."
If the recognizer mishears me: I say "Wrong, last word paper," and the device says "Got it. Let's continue."
If the Pi slips up: I say "Wrong!" or press the button, and the device says "Busted! I said candle, but it was laptop."


4. (optional) Integrate [input devices](inputs.md) in the system

We added a SparkFun Qwiic Button for the call-out and the status LED.

## Prototype your system

The system should:
* use the Raspberry Pi
* use one or more sensors
* require participants to speak to it

*Document how the system works.*

The Pi says a word. You repeat the whole list and add one new word, then the Pi repeats everything and adds its own. Survive 10 rounds to win. If the recognizer mishears you, call it out and fix the word. If the Pi slips up on purpose, call that out instead.

*Include videos or screencaptures of both the system and the controller.*

<img width="3520" height="1980" alt="IMG_8621" src="https://github.com/user-attachments/assets/e3718065-be94-4f0f-8d1f-584defbcea4c" />

https://youtu.be/b-19xku7f0A

## Test the system

Try to get at least two people to interact with your system. (Ideally, you would inform them that there is a wizard *after* the interaction, but we recognize that can be hard.)

https://youtu.be/YbOrXV_8CM8

Answer the following:

### What worked well about the system and what didn't?

Recognition: base.en transcribed multi-word turns accurately, for example "banana, laptop, dragon, paper".
Intuitive feel: Team 2 said it felt intuitive, "like there is a language model running behind it". There is none. It's only speech-to-text and plain string matching, so well-chosen wording and fast feedback can feel smarter than the logic is.
The concept: Team 1 found it interesting that it tests verbal memory, and thought it would suit road trips.
Recovering from errors: The call-out lets the player correct a recognition mistake instead of losing the game.

### What worked well about the controller and what didn't?

Team 2 said the pauses are too long. Each turn has about 1.5 to 1.8 s of silent processing plus the call-out windows. This is also what I saw when acting out the dialogue, where my subject got confused during the lag and felt like they'd done something wrong.
Team 2 also found it easy to mislead by saying "wrong" even when the Pi was right. If the player calls out their own new word, the Pi has to trust them.
Team 3 worried their first words might be cut off.

### What lessons can you take away from the WoZ interactions for designing a more autonomous version of the system?
Show the thinking time. When I simulated lag, my subject felt they had done something wrong. A real device has real delay, so it needs to show clearly that it's working. Our LED is off while thinking, which can look like the device died. A slow pulse would be better.
we could also explain unusual rules up front. My subject was unsure about the device repeating the whole sequence, since that isn't standard in this game. The intro should state the rules.
Tune the timing to the game. The right silence threshold depends on where players pause (before their new word), not on a default value.

### How could you use your system to create a dataset of interaction? What other sensing modalities would make sense to capture?
If the script logged each turn, we could also save the audio with its transcript, the pause lengths, and when people call out (a real machine error, a false alarm, or an attempt to mislead it, which Team 2 found). Right now the script only prints to the terminal, so logging to a file would be a small addition.

we could also use webcam for gaze and head movement, to show when the player is thinking.
better mechanism to handle noise level and mic distance: both affect recognition accuracy.
multiple microphones, to tell players apart in a multiplayer mode, as Team 1 suggested.

<details>
  <summary><strong>Submission Cleanup Reminder (Click to Expand)</strong></summary>

  **Before submitting your README.md:**
  - This readme.md file has a lot of extra text for guidance.
  - Remove all instructional text and example prompts from this file.
  - You may either delete these sections or use the toggle/hide feature in VS Code to collapse them for a cleaner look.
  - Your final submission should be neat, focused on your own work, and easy to read for grading.
</details>
