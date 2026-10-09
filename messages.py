import re

SHOW_EMOJI = True

BAR_FILLED = "█"
BAR_EMPTY = "░"
LOCK_TEXT = "(locked)"
LOCK_MARK = " 🔒" if SHOW_EMOJI else f" {LOCK_TEXT}"

REACTION_SEEN = "👀"
REACTION_OK = "✅"
REACTION_FAIL = "❌"

ERR_GENERIC = "❌ Download failed. Try again later."
ERR_LOGIN = "🔒 This content is private or needs login. Admin can upload cookies for this site."
ERR_GEO = "🌍 Not available in this region."
ERR_UNSUPPORTED_SITE = "❌ This site is not supported."
ERR_NOT_FOUND = "❌ This video was not found. It may have been removed."
ERR_LIVE = "❌ Live streams and premieres are not supported."
ERR_DRM = "🔐 This video is DRM-protected and cannot be downloaded."
ERR_TOO_LARGE = "❌ File is too large for the current limit. Pick a lower quality."
ERR_TOO_LARGE_DETAIL = "❌ File is {size_mb:.0f} MB, over the {limit_mb} MB limit. Pick a lower quality."
ERR_DURATION = "❌ Video exceeds {minutes} minute limit."
ERR_FORMAT = "❌ The requested quality is not available for this video."
ERR_MERGE = "❌ Could not merge the video and audio streams."
ERR_TIMEOUT = "⏱ The site timed out. Try again later."
ERR_RATE_LIMIT = "🚦 The site is rate-limiting requests. Try again in a few minutes."
ERR_EXTRACTOR = "⚠️ This site's extractor is broken right now. Try again after an update."
ERR_UPLOAD_TIMEOUT = "❌ Upload timed out."
ERR_TELEGRAM_UPLOAD = "❌ Telegram upload failed."
ERR_SOMETHING_WRONG = "❌ Something went wrong."
ERR_BUSY_STORAGE = "⚠️ Server is busy storing files. Try again shortly."
ERR_MEMORY_LOW = "⚠️ Server memory is low. Try again shortly."
ERR_REQUEST_EXPIRED = "This request expired. Send the link again."
ERR_INVALID_QUALITY = "Invalid quality."
ERR_LOCK_ALERT = (
    "🔒 This quality is {size_mb:.0f} MB. Max allowed is {limit_mb} MB. "
    "Set up the Local Bot API Server to unlock."
)
ERR_INVALID_SITE = "❌ Invalid site name."
ERR_COOKIE_TOO_LARGE = "❌ Cookie file is too large."
ERR_NOT_NETSCAPE = "❌ Not a Netscape cookie file. Export with 'Get cookies.txt LOCALLY'."

START_TEMPLATE = (
    "🎬 Send me a video link from any site.\n\n"
    "I'll auto-pick the best quality that fits.\n\n"
    "Commands:\n"
    "/audio <url> — audio only\n"
    "/quality <url> — pick quality manually\n"
    "/status — bot status\n"
    "/help — this message\n\n"
    "{local_api_status_line}\n"
    "{today_stats_line}"
)
LOCAL_API_ON = "✅ Large file support active (up to {limit_mb} MB)"
LOCAL_API_OFF = "⚠️ Large files unavailable. Max 50 MB. Ask admin to set up Local API."
TODAY_LINE = "📈 Today: {count} downloads"
COOLDOWN = "⏳ Wait {seconds:.0f}s before the next request."
FETCHING = "🔍 Fetching info..."
QUEUED = "⏳ Queued. Another download is in progress..."
STARTING = "⬇️ Starting download..."
UPLOADING = "📤 Uploading..."
PROCESSING = "🔄 Processing..."
PICKER = "🎬 {title}\nChoose a quality:"
BATCH_LIMIT = "ℹ️ Only processing first {limit} links."
NO_QUALITY_FITS = "⚠️ No quality fits under {limit_mb} MB. Trying the smallest; it may be rejected.\n"
USAGE_AUDIO = "Usage: /audio <url> or reply to a message containing a link."
USAGE_QUALITY = "Usage: /quality <url> or reply to a message containing a link."
USAGE_BROADCAST = "Usage: /broadcast <message>"
USAGE_COOKIES = "Usage: /cookies <site>"

LABEL_AUDIO = "Audio"
LABEL_HEIGHT = "{height}p"
SIZE_SUFFIX = " ~{size_mb:.0f}MB"

STATUS_TITLE = "📊 Bot Status"
STATUS_DIVIDER = "━━━━━━━━━━━━"
STATUS_PUBLIC_API_UP = "🟢 Public API: Connected"
STATUS_PUBLIC_API_DOWN = "🔴 Public API: Not started"
STATUS_LOCAL_API_UP = "🟢 Local API: Connected"
STATUS_LOCAL_API_DOWN = "🔴 Local API: Not found"
STATUS_MAX_SIZE = "📏 Max file size: {limit_mb} MB"
STATUS_TEMP = "💾 Temp storage: {used_mb:.1f} MB / {limit_mb} MB"
STATUS_ACTIVE = "⬇️ Active downloads: {count}"
STATUS_USERS = "👥 Total users: {count}"
STATUS_UPTIME = "🕐 Uptime: {uptime}"
STATUS_YTDLP_OLD = "⚠️ yt-dlp is {days} days old. Extractors may be broken; update it."
STATUS_YTDLP_OK = "🧩 yt-dlp: {version}"
STATUS_FFMPEG_OK = "🎞 ffmpeg: available"
STATUS_FFMPEG_MISSING = "⚠️ ffmpeg missing: merged formats only"

COOKIES_LIST = "🍪 Saved cookie sites: {sites}\nUsage: /cookies <site>"
COOKIES_NONE = "none"
COOKIES_SEND_FILE = "📎 Send the cookies .txt file for {site} now."
COOKIES_SAVED = "✅ Saved cookies for {site}."

BROADCAST_DONE = "📣 Broadcast done. Sent: {sent}, failed: {failed}."

STATS_TITLE = "📈 Detailed stats"
STATS_TOTALS = "Attempts: {attempts}   Failures: {failures}"
STATS_BY_SITE = "By site:"
STATS_BY_QUALITY = "By quality:"
STATS_LAST_DAYS = "Last 7 days:"
STATS_ERRORS = "Errors:"
STATS_TOP_USERS = "Top users:"
STATS_BULLET = "• {label}: {count}"

PROGRESS_LINE = "⬇️ {bar} {percentage}%\n📦 {downloaded} / {total}\n⚡ {speed}/s{eta}"
ETA_LINE = " · ⏱ {eta}"

CAPTION_TITLE = "🎬 {title}"
CAPTION_SITE = "🌐 {site}"
CAPTION_RESOLUTION = "📺 {resolution}"
CAPTION_DURATION = "⏱ {duration}"
CAPTION_SIZE = "📦 {size_mb:.1f} MB"

_EMOJI_PATTERN = re.compile("[\u2139\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF\u200d\ufe0f\U0001F000-\U0001FAFF]+")


def strip_emoji(text: str) -> str:
    stripped = _EMOJI_PATTERN.sub("", text)
    return "\n".join(re.sub(r" {2,}", " ", line).strip() for line in stripped.split("\n"))


def render(text: str) -> str:
    return text if SHOW_EMOJI else strip_emoji(text)
