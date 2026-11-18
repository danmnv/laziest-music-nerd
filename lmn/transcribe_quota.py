"""Daily reservations for the two scheduled archive passes, stored in the private data repo."""
import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
FILENAME = "transcribe-quota.json"
LATE_MINUTES = 60


def quota_window(now):
    pacific = now.astimezone(PACIFIC)
    tomorrow = pacific.date() + timedelta(days=1)
    reset = datetime.combine(tomorrow, time(), PACIFIC).astimezone(timezone.utc)
    return pacific.date().isoformat(), pacific.hour == 23, reset


def read(path, day):
    if path.exists():
        state = json.loads(path.read_text())
        if state["day"] == day:
            return state
    return {"day": day, "passes": {}}


def write(path, state):
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
    pending.replace(path)


def claim(path, slot, owner, main_minutes, main_limits, late_limits, now):
    day, last_hour, _ = quota_window(now)
    if (slot == "late") != last_hour:
        print("transcripts: skipped outside the scheduled quota window")
        return
    state = read(path, day)
    passes = state["passes"]
    if slot in passes:
        print(f"transcripts: {slot} pass already claimed for {day} Pacific time")
        return
    slot_minutes = LATE_MINUTES if slot == "late" else main_minutes
    remaining = main_minutes + LATE_MINUTES - sum(p["minutes"] for p in passes.values())
    slot_limits = late_limits if slot == "late" else main_limits
    requests = {}
    for model, limit in slot_limits.items():
        used = sum(p["requests"].get(model, 0) for p in passes.values())
        daily_limit = main_limits[model] + late_limits.get(model, 0)
        requests[model] = min(limit, max(0, daily_limit - used))
    passes[slot] = {"owner": owner, "minutes": min(slot_minutes, max(0, remaining)), "requests": requests}
    write(path, state)


def reservation(path, slot, owner, now):
    day, last_hour, reset = quota_window(now)
    state = read(path, day)
    entry = state["passes"].get(slot)
    if (slot == "late") != last_hour or not entry or entry["owner"] != owner or entry.get("complete"):
        return None
    return state, entry, reset


def settle(path, state, entry, minutes, requests):
    entry.update(minutes=minutes, requests=requests, complete=True)
    write(path, state)
