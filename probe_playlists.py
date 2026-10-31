"""Temporary: for recent reviews whose "Listen:" is a YouTube video and no release page was found,
can the album playlist be found on the video's channel or by YouTube search?"""
from lmn import listen, youtube
from lmn.musicbrainz import is_smartlink, norm
from lmn.yt_archive import yt

ups = [u for u in youtube.latest_uploads(50) if youtube.is_review(u)]
n = miss = by_channel = by_search = 0
for u in ups:
    r = youtube.review_from_video(u)
    t = listen.youtube_target(r.get("listen_url"))
    if not t or t[0] != "video":
        continue
    n += 1
    if "release_page" in listen.resolve(r["listen_url"], r["album"]):
        continue
    miss += 1
    key, akey = norm(r["album"]), norm(r["artist_name"])
    v = (yt("videos", part="snippet", id=t[1]).get("items") or [{}])[0].get("snippet", {})
    links = [x for x in listen.URL.findall(v.get("description", "")) if is_smartlink(x)]
    print(f"== {r['artist_name']} - {r['album']} | video: {v.get('title')!r} on {v.get('channelTitle')!r} | smartlinks: {links[:3]}")
    pls = yt("playlists", part="snippet", channelId=v.get("channelId"), maxResults=50).get("items") or []
    hit = [p["snippet"]["title"] for p in pls if key in norm(p["snippet"]["title"])]
    by_channel += bool(hit)
    print(f"   channel playlists: {len(pls)}, naming album: {hit}")
    res = yt("search", part="snippet", type="playlist", q=f"{r['artist_name']} {r['album']}", maxResults=5).get("items") or []
    good = False
    for s in res:
        sn = s["snippet"]
        ok = key in norm(sn["title"]) and (akey in norm(sn["title"]) or akey in norm(sn["channelTitle"]))
        good = good or ok
        print(f"   search: {'OK ' if ok else '   '}{sn['title']!r} by {sn['channelTitle']!r} id={s['id']['playlistId'][:6]}")
    by_search += good
print(f"video links: {n}, no release page: {miss}, album playlist on channel: {by_channel}, by search: {by_search}")
