import re

from config import MAX_DURATION_SEC


class DownloadError(Exception):
    user_message = "❌ Download failed. Try again later."

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail)
        self.detail = detail
        self.user_message = type(self).user_message


class LoginRequiredError(DownloadError):
    user_message = "🔒 This content is private or needs login. Admin can upload cookies for this site."


class GeoBlockedError(DownloadError):
    user_message = "🌍 Not available in this region."


class UnsupportedSiteError(DownloadError):
    user_message = "❌ This site is not supported."


class NotFoundError(DownloadError):
    user_message = "❌ This video was not found. It may have been removed."


class LiveStreamError(DownloadError):
    user_message = "❌ Live streams and premieres are not supported."


class DRMProtectedError(DownloadError):
    user_message = "🔐 This video is DRM-protected and cannot be downloaded."


class FileTooLargeError(DownloadError):
    user_message = "❌ File is too large for the current limit. Pick a lower quality."

    def __init__(self, detail: str = "", size_mb: float = 0.0, limit_mb: int = 0) -> None:
        super().__init__(detail)
        self.size_mb = size_mb
        self.limit_mb = limit_mb
        if size_mb and limit_mb:
            self.user_message = (
                f"❌ File is {size_mb:.0f} MB, over the {limit_mb} MB limit. Pick a lower quality."
            )


class DurationExceededError(DownloadError):
    user_message = f"❌ Video exceeds {MAX_DURATION_SEC // 60} minute limit."


class FormatUnavailableError(DownloadError):
    user_message = "❌ The requested quality is not available for this video."


class MergeFailedError(DownloadError):
    user_message = "❌ Could not merge the video and audio streams."


class NetworkTimeoutError(DownloadError):
    user_message = "⏱ The site timed out. Try again later."


class RateLimitedError(DownloadError):
    user_message = "🚦 The site is rate-limiting requests. Try again in a few minutes."


class ExtractorBrokenError(DownloadError):
    user_message = "⚠️ This site's extractor is broken right now. Try again after an update."


class UnknownDownloadError(DownloadError):
    user_message = "❌ Download failed. Try again later."


ERROR_PATTERNS: tuple[tuple[str, type[DownloadError]], ...] = (
    (r"larger than max-filesize|max-filesize", FileTooLargeError),
    (r"requested format is not available|format not available|no video formats", FormatUnavailableError),
    (r"merging|ffmpeg", MergeFailedError),
    (r"\blive event\b|\bis live\b|\bpremiere", LiveStreamError),
    (r"\bdrm\b|encrypted|widevine", DRMProtectedError),
    (r"log ?in|sign in|\bprivate\b|age[- ]restricted|\bage\b", LoginRequiredError),
    (r"\bgeo|region|country|not available in your", GeoBlockedError),
    (r"\b404\b|not found|removed|\bdeleted\b", NotFoundError),
    (r"\b429\b|too many requests|throttl", RateLimitedError),
    (r"timed out|timeout", NetworkTimeoutError),
    (r"extractor error|bug report|report this issue", ExtractorBrokenError),
    (r"unsupported url|unsupported|no suitable extractor", UnsupportedSiteError),
)


def classify_ytdlp_error(error_string: str) -> DownloadError:
    lowered = error_string.lower()
    for pattern, error_class in ERROR_PATTERNS:
        if re.search(pattern, lowered):
            return error_class(error_string)
    return UnknownDownloadError(error_string)
