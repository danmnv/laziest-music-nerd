"""Temporary live check of lmn.listen.resolve on the newest reviews whose "Listen:" link is YouTube."""
from lmn import listen, youtube

ups = [u for u in youtube.latest_uploads(50) if youtube.is_review(u)]
n = found_album = found_page = 0
for u in ups:
    r = youtube.review_from_video(u)
    if not listen.youtube_target(r.get("listen_url")):
        continue
    n += 1
    out = listen.resolve(r["listen_url"], r["album"])
    found_album += "youtube_album" in out
    found_page += "release_page" in out
    print(f"{r['artist_name']} - {r['album']}: {listen.youtube_target(r['listen_url'])[0]} -> {out}")
print(f"youtube listen links: {n}, album playlist confirmed: {found_album}, release page found: {found_page}")
