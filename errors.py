import re

import messages as msg
from config import MAX_DURATION_SEC


class DownloadError(Exception):
    user_message = msg.ERR_GENERIC

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail)
        self.detail = detail
        self.user_message = type(self).user_message


class LoginRequiredError(DownloadError):
    user_message = msg.ERR_LOGIN


class GeoBlockedError(DownloadError):
    user_message = msg.ERR_GEO


class UnsupportedSiteError(DownloadError):
    user_message = msg.ERR_UNSUPPORTED_SITE


class NotFoundError(DownloadError):
    user_message = msg.ERR_NOT_FOUND


class LiveStreamError(DownloadError):
    user_message = msg.ERR_LIVE


class DRMProtectedError(DownloadError):
    user_message = msg.ERR_DRM


class FileTooLargeError(DownloadError):
    user_message = msg.ERR_TOO_LARGE

    def __init__(self, detail: str = "", size_mb: float = 0.0, limit_mb: int = 0) -> None:
        super().__init__(detail)
        self.size_mb = size_mb
        self.limit_mb = limit_mb
        if size_mb and limit_mb:
            self.user_message = msg.ERR_TOO_LARGE_DETAIL.format(size_mb=size_mb, limit_mb=limit_mb)


class DurationExceededError(DownloadError):
    user_message = msg.ERR_DURATION.format(minutes=MAX_DURATION_SEC // 60)


class FormatUnavailableError(DownloadError):
    user_message = msg.ERR_FORMAT


class MergeFailedError(DownloadError):
    user_message = msg.ERR_MERGE


class NetworkTimeoutError(DownloadError):
    user_message = msg.ERR_TIMEOUT


class RateLimitedError(DownloadError):
    user_message = msg.ERR_RATE_LIMIT


class ExtractorBrokenError(DownloadError):
    user_message = msg.ERR_EXTRACTOR


class UnknownDownloadError(DownloadError):
    user_message = msg.ERR_GENERIC


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
