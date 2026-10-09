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
