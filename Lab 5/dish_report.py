"""
Dish Shame: the morning report.

Python works out the facts from the night log (what was there at bedtime, what is there
now, when dishes showed up, when someone was at the counter) and writes the facts sentence
itself, so the numbers are always right. Qwen only adds one short joke on top. In testing,
a longer Qwen report mixed things up (it said nobody was at the counter when somebody was),
so the joke may not contain numbers, times or names; if it does, or Ollama is not running,
the report is just the facts.

    python dish_report.py --log nights/night_20261028-2310.jsonl
    python dish_report.py --log ... --no-qwen      # template only, no model
"""
import argparse
import collections
import datetime
import json
import re
import time

import requests

from dish_detect import describe, total


def clock(ts):
    """'2026-10-28T01:12:40' -> '1:12 am'"""
    t = datetime.datetime.fromisoformat(ts)
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def facts_from_log(entries):
    looks = [e for e in entries if "dishes" in e]
    if not looks:
        return None
    start, end = looks[0], looks[-1]
    before, after = start["dishes"], end["dishes"]
    new = {d: after.get(d, 0) - before.get(d, 0) for d in after if after.get(d, 0) > before.get(d, 0)}
    gone = {d: before[d] - after.get(d, 0) for d in before if before[d] > after.get(d, 0)}

    # moments when the number of dishes went up, and person visits
    arrivals, visits, prev, was_there = [], [], start, start.get("person", False)
    for e in looks[1:]:
        added = {d: n - prev["dishes"].get(d, 0) for d, n in e["dishes"].items() if n > prev["dishes"].get(d, 0)}
        if added:
            arrivals.append({"t": e["t"], "added": added})
        if e.get("person") and not was_there:
            visits.append(e["t"])
        was_there = e.get("person", False)
        prev = e
    busiest = None
    if arrivals:
        hours = collections.Counter()
        for a in arrivals:
            hours[datetime.datetime.fromisoformat(a["t"]).hour] += total(a["added"])
        h = hours.most_common(1)[0][0]
        busiest = f"{h % 12 or 12} {'am' if h < 12 else 'pm'}"

    return {
        "from": clock(start["t"]), "to": clock(end["t"]),
        "at_bedtime": before, "now": after, "new": new, "gone": gone,
        "arrivals": arrivals, "visits": visits, "busiest_hour": busiest,
        "shame": total(new) > 0,
    }


def fact_sheet(f):
    lines = [
        f"- Watched the counter from {f['from']} to {f['to']}.",
        f"- At bedtime: {describe(f['at_bedtime'])}.",
        f"- This morning: {describe(f['now'])}.",
        f"- New since bedtime: {describe(f['new'])}.",
    ]
    if f["gone"]:
        lines.append(f"- Gone since bedtime (someone cleaned up): {describe(f['gone'])}.")
    for a in f["arrivals"][:6]:
        lines.append(f"- At {clock(a['t'])}: {describe(a['added'])} appeared.")
    if f["visits"]:
        lines.append(f"- Someone was at the counter {len(f['visits'])} time(s), first at {clock(f['visits'][0])}.")
    else:
        lines.append("- Nobody was seen at the counter.")
    return "\n".join(lines)


def template(f):
    """The facts sentence. Always written by Python, so it is always right."""
    if f["shame"]:
        when = f", mostly around {f['busiest_hour']}" if f["busiest_hour"] else ""
        return f"{describe(f['new']).capitalize()} showed up on the counter overnight{when}."
    if f["gone"]:
        return f"Someone cleaned up overnight: {describe(f['gone'])} gone."
    return "The counter stayed clean all night. Nice."


def ask_qwen(f, model="qwen3.5:0.8b"):
    """One short joke about the night. The facts sentence comes from Python."""
    prompt = f"""You are Dish Shame, a sassy little gadget that watches the kitchen counter at night.
This morning's news: {template(f)}

Write ONE short, funny sentence (at most 15 words) reacting to this news, for sleepy roommates.
Do not use any numbers, times or names. Do not blame a specific person."""
    t0 = time.time()
    r = requests.post("http://localhost:11434/api/generate", json={
        "model": model, "prompt": prompt, "think": False, "stream": False,
        "options": {"temperature": 0.7, "num_predict": 40}}, timeout=600)
    r.raise_for_status()
    joke = r.json()["response"].encode("ascii", "ignore").decode()    # emojis: the screen can't draw them
    return " ".join(joke.split()).strip('"'), time.time() - t0


NUMBER_WORDS = r"\b(one|two|three|four|five|six|seven|eight|nine|ten|dozen|o'clock|midnight|am|pm)\b"


def joke_ok(text):
    """No digits, no number or time words, one short sentence."""
    return (bool(text) and not re.search(r"\d", text) and not re.search(NUMBER_WORDS, text.lower())
            and len(text.split()) <= 22)


def morning_report(entries, model="qwen3.5:0.8b", use_qwen=True):
    """Returns (facts, report text, where the text came from)."""
    f = facts_from_log(entries)
    if f is None:
        return None, "I didn't get a single look at the counter last night. Is the camera plugged in?", "template"
    facts = template(f)
    if not use_qwen or not (f["shame"] or f["gone"]):
        return f, facts, "template"                 # a quiet night needs no language model
    try:
        joke, took = ask_qwen(f, model)
        if joke_ok(joke):
            return f, f"{facts} {joke}", f"facts + qwen joke ({took:.0f} s)"
        print(f"[report] Qwen's joke broke the rules, leaving it out:\n  {joke}")
    except Exception as e:
        print(f"[report] Qwen not available ({type(e).__name__}), facts only")
    return f, facts, "template"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--model", default="qwen3.5:0.8b")
    parser.add_argument("--no-qwen", action="store_true")
    args = parser.parse_args()
    entries = [json.loads(line) for line in open(args.log) if line.strip()]
    f, text, source = morning_report(entries, args.model, not args.no_qwen)
    if f:
        print(fact_sheet(f))
    print(f"\n[{source}] {text}")
