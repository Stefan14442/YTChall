import os
import re
import requests
from flask import Flask, render_template, request
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    raise ValueError("Set YOUTUBE_API_KEY in environment variables!")

# Realistic CPM ranges by category
CATEGORY_CPM = {
    "Gaming": (1.0, 3.0),
    "Education": (2.0, 8.0),
    "Finance": (5.0, 15.0),
    "Entertainment": (1.0, 4.0),
    "Tech": (4.0, 10.0),
    "Default": (1.5, 5.0),
}

def extract_channel_id(url):
    pattern = r"(?:youtube\.com\/(channel|user|@))([\w\-]+)"
    match = re.search(pattern, url)
    if not match:
        return None
    kind, identifier = match.groups()
    if kind == "channel":
        return identifier
    if kind == "@" or kind == "user":
        param = "forHandle" if kind == "@" else "forUsername"
        r = requests.get(
            f"https://www.googleapis.com/youtube/v3/channels?part=id&{param}={identifier}&key={YOUTUBE_API_KEY}"
        ).json()
        return r["items"][0]["id"] if r.get("items") else None

@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    result = None
    if request.method == "POST":
        url = request.form.get("channel_url", "").strip()
        user_cpm = request.form.get("custom_cpm")
        monetized_pct = float(request.form.get("monetized_pct", "80")) / 100

        channel_id = extract_channel_id(url)
        if not channel_id:
            error = "❌ Invalid YouTube URL."
        else:
            resp = requests.get(
                f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,contentDetails&id={channel_id}&key={YOUTUBE_API_KEY}"
            ).json()
            items = resp.get("items")
            if not items:
                error = "❌ Channel not found."
            else:
                data = items[0]
                stats, snip, cont = data["statistics"], data["snippet"], data["contentDetails"]
                subs = int(stats.get("subscriberCount", 0))
                total_views = int(stats.get("viewCount", 0))
                vid_count = int(stats.get("videoCount", 0))
                title = snip.get("title")
                thumb = snip.get("thumbnails", {}).get("high", {}).get("url")
                ctr_country = snip.get("country", "Unknown")

                # Choose CPM: user input or category-based default
                default_low, default_high = CATEGORY_CPM["Default"]
                chosen_low, chosen_high = (default_low, default_high)
                cpm_note = "Default CPM used"
                if user_cpm:
                    try:
                        val = float(user_cpm)
                        chosen_low = chosen_high = val
                        cpm_note = "Custom CPM used"
                    except:
                        pass

                # Estimate earnings
                avg_views_per_sub = total_views / max(subs, 1) if subs else 0
                monthly_views = subs * avg_views_per_sub
                monetized_views = monthly_views * monetized_pct
                low_earn = (monetized_views / 1000) * chosen_low
                high_earn = (monetized_views / 1000) * chosen_high

                # Top 5 videos
                upload_pl = cont["relatedPlaylists"]["uploads"]
                pl = requests.get(
                    f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId={upload_pl}&key={YOUTUBE_API_KEY}"
                ).json().get("items", [])
                vids = [i["snippet"]["resourceId"]["videoId"] for i in pl]
                viddata = requests.get(
                    f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id={','.join(vids)}&key={YOUTUBE_API_KEY}"
                ).json().get("items", [])
                top5 = sorted(viddata, key=lambda x: int(x["statistics"].get("viewCount", 0)), reverse=True)[:5]
                top_videos = [{"title": v["snippet"]["title"],
                               "thumbnail": v["snippet"]["thumbnails"]["medium"]["url"],
                               "views": int(v["statistics"].get("viewCount", 0)),
                               "url": f"https://www.youtube.com/watch?v={v['id']}"}
                              for v in top5]

                result = {
                    "url": url, "title": title, "thumb": thumb, "subs": subs,
                    "total_views": total_views, "vid_count": vid_count,
                    "low_earn": f"{low_earn:,.2f}", "high_earn": f"{high_earn:,.2f}",
                    "cpm_note": cpm_note, "chosen_low": chosen_low, "chosen_high": chosen_high,
                    "top_videos": top_videos
                }

    return render_template("index.html", error=error, result=result)

if __name__ == "__main__":
    app.run(debug=True)
