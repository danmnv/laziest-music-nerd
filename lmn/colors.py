"""Score -> color. Spec: green 8-10, neutral 5-7, red <=4 and NOT GOOD. CLASSIC (off-scale) counts as green."""

EMOJI = {"green": "🟢", "neutral": "🟡", "red": "🔴", None: "⚪"}


def color(score, not_good=False, classic=False):
    if not_good:
        return "red"
    if classic:
        return "green"
    if score is None:
        return None
    if score >= 8:
        return "green"
    if score >= 5:
        return "neutral"
    return "red"


def label(score, not_good=False, classic=False, unknown="—"):
    if not_good:
        return "NOT GOOD"
    if classic:
        return "CLASSIC"
    if score is None:
        return unknown
    return f"{score:g}"
