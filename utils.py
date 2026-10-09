import os
import random
import re
from datetime import date
from urllib.parse import urlparse

import yt_dlp

import config
import messages as msg
from messages import render

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
TRAILING_PUNCTUATION = ".,;:!?)]}"


MOBILE_UA_POOL = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; moto g power) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; CPH2581) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; V2230) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
)


def extract_urls(text: str) -> list[str]:
    return [match.rstrip(TRAILING_PUNCTUATION) for match in URL_PATTERN.findall(text)]


def is_fetchable_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def human_size(size_bytes: float) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} GB"


def human_duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_uptime(seconds: float) -> str:
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    return f"{days}d {hours}h {minutes}m"


def sanitize_filename(name: str, max_len: int = 100) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name).strip()
    return cleaned[:max_len] or "video"


def random_ua() -> str:
    return random.choice(MOBILE_UA_POOL)


def extract_site_name(url: str) -> str:
    hostname = (urlparse(url).hostname or "unknown").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def format_caption(
    title: str,
    site: str | None,
    resolution: str | None,
    duration: int | None,
    file_size_mb: float,
) -> str:
    lines = [msg.CAPTION_TITLE.format(title=title)]
    if site:
        lines.append(msg.CAPTION_SITE.format(site=site))
    if resolution:
        lines.append(msg.CAPTION_RESOLUTION.format(resolution=resolution))
    if duration:
        lines.append(msg.CAPTION_DURATION.format(duration=human_duration(duration)))
    lines.append(msg.CAPTION_SIZE.format(size_mb=file_size_mb))
    return render("\n".join(lines))[:1024]


def yt_dlp_age_days() -> int:
    try:
        year, month, day = (int(part) for part in yt_dlp.version.__version__.split(".")[:3])
        return (date.today() - date(year, month, day)).days
    except (ValueError, TypeError):
        return -1


def is_memory_pressure() -> bool:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    available_kb = int(line.split()[1])
                    return available_kb < config.MEMORY_PRESSURE_MB * 1024
    except (OSError, ValueError, IndexError):
        return False
    return False


def file_size_megabytes(file_path: str) -> float:
    return os.path.getsize(file_path) / config.MEGABYTE
