"""Temporary probe: can the transcript give a score where TND has no score tag? Checked first against reviews
that have a tag."""
import random
import re
from collections import Counter

from lmn import http, tnd

# (1) transcripts
agree = disagree = tagged_found = tagged = 0
untagged = untagged_found = 0
by_year, found_by_year, samples, wrong = Counter(), Counter(), [], []
page = 1
while page:
    d = tnd.fetch_posts(limit=100, page=page, with_text=True)
    for p in d["posts"]:
        r = tnd.parse_post(p)
        v = tnd.parse_verdict(p.get("plaintext"))
        has_tag = r.get("score") is not None or r.get("not_good") or r.get("classic")
        if r.get("guest"):
            continue
        if has_tag:
            tagged += 1
            if "score" in v and r.get("score") is not None:
                tagged_found += 1
                if v["score"] == r["score"]:
                    agree += 1
                else:
                    disagree += 1
                    if len(wrong) < 8:
                        wrong.append((r["title"], r["score"], v))
        else:
            untagged += 1
            y = r["published"][:4]
            by_year[y] += 1
            if v:
                untagged_found += 1
                found_by_year[y] += 1
                if len(samples) < 10 and random.random() < 0.05:
                    samples.append((r["title"], v, (p.get("plaintext") or "")[-160:].replace("\n", " ")))
    page = d["meta"]["pagination"].get("next")
print(f"TAGGED (non-guest): {tagged}; transcript score found: {tagged_found}; equal to tag: {agree}; different: {disagree}")
for w in wrong:
    print("   differs:", w)
print(f"UNTAGGED (non-guest): {untagged}; transcript verdict found: {untagged_found}")
print("   by year (found/total):", {y: f"{found_by_year[y]}/{n}" for y, n in sorted(by_year.items())})
for s in samples:
    print("   sample:", s)

