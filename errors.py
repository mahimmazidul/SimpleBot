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
