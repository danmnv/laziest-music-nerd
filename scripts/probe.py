"""One-off diagnostics for the 'check at start of build' list. Prints findings only, never secret values."""
import os, re, json, sys, urllib.request, urllib.parse, html

UA = "LaziestMusicNerd/0.1 (https://github.com/danmnv/laziest-music-nerd)"

def get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, repr(e)

def section(t): print("\n" + "=" * 20, t, "=" * 20, flush=True)

section("SECRETS PRESENT")
for k in ["TELEGRAM_BOT_TOKEN","TELEGRAM_CHANNEL","GEMINI_API_KEY","YOUTUBE_API_KEY","CLOUDFLARE_API_TOKEN","CLOUDFLARE_ACCOUNT_ID","ODESLI_API_KEY"]:
    print(k, "set" if os.environ.get(k) else "MISSING")

section("RSS")
for u in ["https://theneedledrop.com/album-reviews/rss/", "https://theneedledrop.com/rss/"]:
    s, b = get(u)
    items = re.findall(r"<item>(.*?)</item>", b, re.S)
    print(u, s, "items:", len(items))
    for it in items[:40]:
        t = re.search(r"<title>(.*?)</title>", it, re.S); l = re.search(r"<link>(.*?)</link>", it, re.S)
        d = re.search(r"<pubDate>(.*?)</pubDate>", it); cats = re.findall(r"<category>(.*?)</category>", it)
        print("  ", d and d.group(1), "|", t and t.group(1)[:90], "|", l and l.group(1), "|", cats[:6])
    if items:
        print("FIRST ITEM RAW (2000 chars):", items[0][:2000])

section("POST META")
s, b = get("https://theneedledrop.com/album-reviews/")
links = list(dict.fromkeys(re.findall(r'href="(/album-reviews/[^"/]+/)"', b)))
print("listing links:", len(links))
for p in links[:10]:
    s, b = get("https://theneedledrop.com" + p)
    metas = re.findall(r"<meta[^>]+>", b)
    keep = [m for m in metas if re.search(r'twitter:|og:|article:|description', m)]
    print("\n---", p, s)
    for m in keep: print("  ", m[:300])
    c = re.search(r'<link rel="canonical"[^>]*>', b); print("   canonical:", c and c.group(0))
    yt = set(re.findall(r'(?:youtube\.com/embed/|youtu\.be/|watch\?v=)([\w-]{11})', b)); print("   yt ids:", yt)
    k = re.search(r'data-key="([0-9a-f]{20,})"', b); print("   ghost content key present:", bool(k))
    body = re.search(r'<section class="gh-content[^"]*">(.*?)</section>', b, re.S) or re.search(r'<div class="gh-content[^"]*">(.*?)</div>\s*</', b, re.S)
    text = re.sub(r"<[^>]+>", " ", body.group(1)) if body else ""
    text = html.unescape(re.sub(r"\s+", " ", text))
    print("   body chars:", len(text)); print("   body head:", text[:700]); print("   body tail:", text[-500:])

section("GHOST CONTENT API")
s, b = get("https://theneedledrop.com/")
k = re.search(r'data-key="([0-9a-f]{20,})"', b); api = re.search(r'data-api="([^"]+)"', b)
print("key:", bool(k), "api:", api and api.group(1))
if k:
    base = (api.group(1) if api else "https://theneedledrop.com/ghost/api/content/").rstrip("/")
    s, b = get(f"{base}/posts/?key={k.group(1)}&limit=3&fields=title,slug,published_at,custom_excerpt,url&include=tags")
    print("posts", s, b[:1500])
    s, b = get(f"{base}/tags/?key={k.group(1)}&limit=all&fields=name,slug&filter=visibility:public")
    print("tags", s, b[:1500])
    s, b = get(f"{base}/posts/?key={k.group(1)}&limit=1&order=published_at%20asc&fields=title,published_at,url&filter=tag:album-reviews")
    print("oldest in album-reviews:", s, b[:800])
    s, b = get(f"{base}/posts/?key={k.group(1)}&limit=1&fields=title&filter=tag:album-reviews")
    m = re.search(r'"total":(\d+)', b); print("total album-reviews:", m and m.group(1))

section("ARCHIVE DEPTH (pagination)")
lo, hi = 1, 2000
s, _ = get(f"https://theneedledrop.com/album-reviews/page/{hi}/")
print("page", hi, s)
while lo < hi:
    mid = (lo + hi + 1) // 2
    s, _ = get(f"https://theneedledrop.com/album-reviews/page/{mid}/")
    if s == 200: lo = mid
    else: hi = mid - 1
print("last page:", lo)
s, b = get(f"https://theneedledrop.com/album-reviews/page/{lo}/")
print("last page titles:", re.findall(r'<h\d[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h\d>', b, re.S)[-5:])
print("last page dates:", re.findall(r'datetime="([^"]+)"', b)[-5:])

section("RATING STRINGS ACROSS PAGES")
seen = {}
for pg in [1, 5, 20, 50, 100, max(lo // 2, 1), lo]:
    s, b = get(f"https://theneedledrop.com/album-reviews/page/{pg}/")
    for p in list(dict.fromkeys(re.findall(r'href="(/album-reviews/[^"/]+/)"', b)))[:4]:
        s2, b2 = get("https://theneedledrop.com" + p)
        m = re.search(r'name="twitter:data2" content="([^"]*)"', b2); l1 = re.search(r'name="twitter:label2" content="([^"]*)"', b2)
        d = re.search(r'article:published_time" content="([^"]*)"', b2)
        print(pg, d and d.group(1)[:10], "|", l1 and l1.group(1), "|", m and html.unescape(m.group(1)), "|", p)

section("MELONDY")
for u in ["https://melondy.com/", "https://melondy.com/robots.txt", "https://melondy.com/terms", "https://melondy.com/api"]:
    s, b = get(u); print(u, s, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b))[:800])

section("SONG.LINK")
s, b = get("https://api.song.link/v1-alpha.1/links?url=" + urllib.parse.quote("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
print(s, b[:300])

section("MUSICBRAINZ")
q = urllib.parse.quote('releasegroup:"Dopamine Chamber" AND artist:"Fontaines D.C."')
s, b = get(f"https://musicbrainz.org/ws/2/release-group/?query={q}&fmt=json&limit=2"); print(s, b[:800])

section("BANDCAMP")
s, b = get("https://bandcamp.com/search?q=" + urllib.parse.quote("Shabazz Palaces It's a Style Sport") + "&item_type=a")
print(s, re.findall(r'<div class="heading">\s*<a href="([^"]+)"', b)[:3])

section("DEEZER")
s, b = get("https://api.deezer.com/search/album?q=" + urllib.parse.quote('artist:"Fontaines D.C." album:"Dopamine Chamber"')); print(s, b[:500])

section("YOUTUBE")
key = os.environ.get("YOUTUBE_API_KEY")
if key:
    s, b = get("https://www.googleapis.com/youtube/v3/channels?part=contentDetails,statistics&forHandle=@theneedledrop&key=" + key)
    print("channel", s, re.sub(key, "***", b)[:600])
    s, b = get("https://www.googleapis.com/youtube/v3/search?part=snippet&type=playlist&maxResults=3&q=" + urllib.parse.quote("Fontaines D.C. Dopamine Chamber album") + "&key=" + key)
    print("playlist search", s, re.sub(key, "***", b)[:1200])

section("TELEGRAM")
tok = os.environ.get("TELEGRAM_BOT_TOKEN")
if tok:
    s, b = get(f"https://api.telegram.org/bot{tok}/getMe"); print("getMe", s, b.replace(tok, "***")[:300])
    ch = os.environ.get("TELEGRAM_CHANNEL")
    if ch:
        s, b = get(f"https://api.telegram.org/bot{tok}/getChat?chat_id=" + urllib.parse.quote(ch)); print("getChat", s, b.replace(tok, "***")[:400])
        s, b = get(f"https://api.telegram.org/bot{tok}/getChatMember?chat_id=" + urllib.parse.quote(ch) + "&user_id=" + b"".decode() + tok.split(":")[0]); print("bot member", s, b.replace(tok, "***")[:400])
    s, b = get(f"https://api.telegram.org/bot{tok}/getUpdates"); 
    ids = set(re.findall(r'"chat":\{"id":(-?\d+)[^}]*"type":"private"', b)); print("private chats seen in updates:", len(ids))

section("GEMINI")
gk = os.environ.get("GEMINI_API_KEY")
if gk:
    s, b = get("https://generativelanguage.googleapis.com/v1beta/models?key=" + gk)
    print(s, [m for m in re.findall(r'"name": "models/([^"]+)"', b) if "flash" in m][:15])
