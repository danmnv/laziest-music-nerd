"""One-off diagnostics, round 2. Prints findings only, never secret values."""
import os, re, json, urllib.request, urllib.parse, html, collections

UA = "LaziestMusicNerd/0.1 (https://github.com/danmnv/laziest-music-nerd)"
def get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), url
    except Exception as e:
        return 0, repr(e), url
def section(t): print("\n" + "=" * 20, t, "=" * 20, flush=True)

s, b, _ = get("https://theneedledrop.com/")
KEY = re.search(r'data-key="([0-9a-f]{20,})"', b).group(1)
API = "https://theneedledrop.com/ghost/api/content"

section("ALL ALBUM REVIEWS VIA GHOST API")
posts, page = [], 1
while page:
    s, b, _ = get(f"{API}/posts/?key={KEY}&limit=100&page={page}&filter=tag:album-reviews&fields=title,slug,published_at,url,canonical_url,custom_excerpt,feature_image&include=tags")
    d = json.loads(b); posts += d["posts"]; page = d["meta"]["pagination"]["next"]
print("fetched", len(posts))
rate_re = re.compile(r"(\d+(\.\d+)?\s*/\s*10|not good|not bad|classic|light|strong|decent|^\d+$|/10)", re.I)
tagc = collections.Counter(); none = []; per_year = collections.Counter(); per_year_none = collections.Counter()
for p in posts:
    names = [t["name"] for t in p["tags"]]
    r = [n for n in names if rate_re.search(n)]
    for n in r: tagc[n.lower()] += 1
    y = p["published_at"][:4]; per_year[y] += 1
    if not any(re.fullmatch(r"\s*(\d+(\.\d+)?)\s*/\s*10\s*", n) or n.lower() == "not good" for n in names):
        none.append(p); per_year_none[y] += 1
print("rating-like tags:", tagc.most_common(80))
print("per year total / without N/10 or not good:")
for y in sorted(per_year): print("  ", y, per_year[y], per_year_none[y])
print("examples without rating tag (recent first):")
for p in none[:25]: print("  ", p["published_at"][:10], "|", p["title"], "|", [t["name"] for t in p["tags"]][:10])
print("canonical non-youtube:", sum(1 for p in posts if "youtu" not in (p.get("canonical_url") or "")))
print("titles patterns:", collections.Counter(("dash" if " - " in p["title"] else "NOTGOOD" if "NOT GOOD" in p["title"].upper() else "other") for p in posts))
print("other-title examples:", [p["title"] for p in posts if " - " not in p["title"]][:40])
print("guest:", [p["title"] for p in posts if "guest" in p["title"].lower()][:10])
print("type-ish tags:", collections.Counter(t["name"].lower() for p in posts for t in p["tags"] if re.search(r"\bep\b|live|mixtape|compilation|deluxe|single|soundtrack|remix", t["name"], re.I)).most_common(30))
print("decimal ratings in titles/excerpts:", [p["title"] for p in posts if re.search(r"\d\.\d/10", json.dumps(p))][:10])

section("ONE POST FULL BODY")
s, b, _ = get(f"{API}/posts/slug/fontaines-dc-dopamine-chamber-album-review-uzvthnau6nc/?key={KEY}&formats=html,plaintext")
p = json.loads(b)["posts"][0]
txt = p.get("plaintext") or re.sub(r"<[^>]+>", " ", p.get("html") or "")
print("keys:", list(p.keys())); print("chars:", len(txt)); print("HEAD:", txt[:1500]); print("TAIL:", txt[-1200:])
print("html head:", (p.get("html") or "")[:800])

section("SONG.LINK WEB")
for u in ["https://song.link/" + "https://www.deezer.com/album/1103270092", "https://album.link/" + "https://www.deezer.com/album/1103270092", "https://song.link/search?q=" + urllib.parse.quote("Fontaines D.C. Dopamine Chamber")]:
    s, b, fu = get(u); t = re.search(r"<title>(.*?)</title>", b, re.S)
    print(u, s, fu, t and t.group(1)[:150], "| has spotify:", "open.spotify.com" in b, "| apple:", "music.apple.com" in b)

section("BANDCAMP SEARCH RAW")
s, b, _ = get("https://bandcamp.com/search?q=" + urllib.parse.quote("Shabazz Palaces It's a Style Sport") + "&item_type=a")
print(s, len(b)); i = b.find("searchresult"); print(b[i-200:i+2500] if i >= 0 else b[:1500])

section("MUSICBRAINZ DURATION + COVER")
s, b, _ = get("https://musicbrainz.org/ws/2/release/843f8feb-aed0-4e76-87c9-5fa0f2053796?inc=recordings+artist-credits&fmt=json")
d = json.loads(b); ms = sum((t.get("length") or 0) for m in d.get("media", []) for t in m.get("tracks", [])); print("duration min", ms / 60000, "tracks", sum(len(m.get("tracks", [])) for m in d.get("media", [])))
s, b, fu = get("https://coverartarchive.org/release-group/8897af6d-f344-4ad4-af70-83cb425d8397/front-500"); print("CAA", s, fu[:120], len(b))
s, b, _ = get("https://musicbrainz.org/ws/2/artist/fd87acc7-e0a0-4a45-bc2a-d2ab5c10be68?inc=aliases+release-groups&fmt=json")
d = json.loads(b); print("artist:", d.get("type"), d.get("country"), d.get("life-span"), "rgs:", len(d.get("release-groups", [])), [a["name"] for a in d.get("aliases", [])][:5])

section("DEEZER ALBUM")
s, b, _ = get("https://api.deezer.com/album/1103270092"); d = json.loads(b)
print({k: d.get(k) for k in ["title", "duration", "nb_tracks", "record_type", "release_date", "cover_xl", "upc"]}, d.get("artist", {}).get("name"))
