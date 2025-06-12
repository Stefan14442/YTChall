import os
import re
import time
import requests
from flask import Flask, render_template, request, url_for
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
app = Flask(__name__)

# Configuration
app.config['YOUTUBE_API_KEY'] = os.getenv("YOUTUBE_API_KEY")
app.config['SITE_NAME'] = "YouTube Earnings Estimator"
app.config['CONTACT_EMAIL'] = "support@youtubeeestimator.com"
app.config['GA_TRACKING_ID'] = os.getenv("GA_TRACKING_ID", "")

if not app.config['YOUTUBE_API_KEY']:
    raise ValueError("YOUTUBE_API_KEY not set in .env")

# Rate limiting (1 request per second to comply with YouTube API limits)
last_request = 0
RATE_LIMIT_DELAY = 1.0


def rate_limit():
    global last_request
    now = time.time()
    delay = RATE_LIMIT_DELAY - (now - last_request)
    if delay > 0:
        time.sleep(delay)
    last_request = time.time()


def extract_channel_id(url):
    """Extract channel ID from various YouTube URL formats"""
    patterns = [
        r"youtube\.com/channel/([a-zA-Z0-9_-]+)",  # Channel ID format
        r"youtube\.com/@([a-zA-Z0-9_-]+)",  # Handle format
        r"youtube\.com/c/([a-zA-Z0-9_-]+)",  # Custom URL format
        r"youtube\.com/user/([a-zA-Z0-9_-]+)",  # Legacy user format
        r"youtu\.be/([a-zA-Z0-9_-]+)"  # Short URL format
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_channel_id_from_handle(handle):
    """Convert @handle to channel ID using YouTube API"""
    rate_limit()
    try:
        url = f"https://www.googleapis.com/youtube/v3/search?part=id&type=channel&q={handle}&key={app.config['YOUTUBE_API_KEY']}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get('items'):
            return data['items'][0]['id']['channelId']
    except Exception as e:
        app.logger.error(f"Error converting handle to channel ID: {e}")
    return None


def get_channel_stats(channel_identifier):
    """Fetch channel statistics from YouTube API"""
    # First determine if we have a channel ID or handle
    if channel_identifier.startswith('UC'):
        # Likely a channel ID (starts with UC)
        channel_id = channel_identifier
    else:
        # Probably a handle (@username)
        channel_id = get_channel_id_from_handle(channel_identifier)
        if not channel_id:
            return None

    rate_limit()
    try:
        url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id={channel_id}&key={app.config['YOUTUBE_API_KEY']}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        res = response.json()

        if not res.get("items"):
            return None

        item = res["items"][0]
        return {
            "title": item["snippet"]["title"],
            "subscribers": int(item["statistics"].get("subscriberCount", 0)),
            "views": int(item["statistics"].get("viewCount", 0)),
            "videos": int(item["statistics"].get("videoCount", 0)),
            "thumbnail": item["snippet"]["thumbnails"]["high"]["url"],
            "description": item["snippet"].get("description", ""),
            "published": format_date(item["snippet"].get("publishedAt", "")),
            "channel_id": channel_id,
            "handle": f"@{item['snippet'].get('customUrl', '').replace('@', '')}" if item['snippet'].get(
                'customUrl') else None
        }
    except requests.exceptions.RequestException as e:
        app.logger.error(f"YouTube API request failed: {e}")
        return None


def format_date(date_str):
    """Format ISO date to human-readable format"""
    if not date_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime("%B %d, %Y")
    except ValueError:
        return date_str


def estimate_earnings(view_count, cpm, monetized_pct):
    """Calculate estimated earnings with validation"""
    try:
        cpm = float(cpm)
        monetized_pct = float(monetized_pct)

        if not (0 <= monetized_pct <= 100):
            raise ValueError("Monetized percentage must be between 0 and 100")

        monetized = view_count * (monetized_pct / 100)
        earnings = (monetized / 1000) * cpm
        return round(earnings, 2), None  # Ensure earnings are rounded to 2 decimal places
    except (ValueError, TypeError) as e:
        return 0, str(e)


@app.context_processor
def inject_globals():
    """Make variables available to all templates"""
    return {
        'site_name': app.config['SITE_NAME'],
        'current_year': datetime.now().year,
        'ga_tracking_id': app.config['GA_TRACKING_ID']
    }


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    default_cpm = 4.0
    default_monetized_pct = 80

    if request.method == "POST":
        url = request.form.get("channel_url", "").strip()
        cpm = request.form.get("custom_cpm", str(default_cpm)).strip()
        monetized_pct = request.form.get("monetized_pct", str(default_monetized_pct))

        if not url:
            error = "Please enter a YouTube channel URL."
        else:
            channel_identifier = extract_channel_id(url)
            if not channel_identifier:
                error = "Invalid or unsupported URL format. Please use a full YouTube channel URL."
            else:
                stats = get_channel_stats(channel_identifier)
                if not stats:
                    error = "Could not fetch channel info. Please check the URL and try again."
                else:
                    try:
                        avg_views = stats["views"] / max(stats["videos"], 1)
                        monthly_views = avg_views * 30

                        earnings, calc_error = estimate_earnings(
                            monthly_views,
                            cpm,
                            monetized_pct
                        )

                        if calc_error:
                            error = calc_error
                        else:
                            result = {
                                "channel": stats,
                                "monthly_views": int(monthly_views),
                                "earnings": earnings,
                                "cpm": float(cpm),
                                "monetized_pct": float(monetized_pct),
                                "daily_views": int(avg_views),
                                "yearly_earnings": round(earnings * 12, 2)
                            }
                    except Exception as e:
                        app.logger.error(f"Calculation error: {e}")
                        error = "An error occurred during calculation. Please try again."

    return render_template("index.html",
                           result=result,
                           error=error,
                           default_cpm=default_cpm,
                           default_monetized_pct=default_monetized_pct)


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


# Custom filters
@app.template_filter('comma')
def comma_format(value):
    """Format numbers with commas"""
    return "{:,}".format(value)


@app.template_filter('money')
def money_format(value):
    """Format money with 2 decimal places"""
    return "${:,.2f}".format(value)


if __name__ == "__main__":
    app.run(debug=False)