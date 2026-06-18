from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse

import requests


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
SONG_STREAM_KEYWORDS = [
    "歌枠",
    "karaoke",
    "singing",
    "sing",
    "カラオケ",
    "弾き語り",
    "歌ってみた",
    "setlist",
]


class YouTubeAPIError(RuntimeError):
    pass


class CommentsDisabledError(YouTubeAPIError):
    pass


class QuotaExceededError(YouTubeAPIError):
    pass


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: str
    title: str
    uploads_playlist_id: str


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    published_at: str | None


@dataclass(frozen=True)
class CommentInfo:
    comment_id: str
    text: str
    author: str
    published_at: str | None


class YouTubeClient:
    def __init__(self, api_key: str, timeout: int = 45, max_retries: int = 5) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def get_video(self, video_id: str) -> VideoInfo:
        data = self._get(
            "videos",
            {
                "part": "snippet",
                "id": video_id,
                "maxResults": 1,
            },
        )
        items = data.get("items", [])
        if not items:
            raise YouTubeAPIError(f"Video not found: {video_id}")

        item = items[0]
        snippet = item["snippet"]
        return VideoInfo(
            video_id=item["id"],
            title=snippet.get("title", ""),
            channel_id=snippet.get("channelId", ""),
            channel_title=snippet.get("channelTitle", ""),
            published_at=snippet.get("publishedAt"),
        )

    def get_comments(self, video_id: str, max_comments: int | None = None) -> Iterator[CommentInfo]:
        yielded = 0
        page_token: str | None = None

        while True:
            params = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": 100,
                "textFormat": "plainText",
                "order": "relevance",
            }
            if page_token:
                params["pageToken"] = page_token

            data = self._get("commentThreads", params)
            for item in data.get("items", []):
                top_comment = item["snippet"]["topLevelComment"]
                snippet = top_comment["snippet"]
                yield CommentInfo(
                    comment_id=top_comment["id"],
                    text=snippet.get("textDisplay", ""),
                    author=snippet.get("authorDisplayName", ""),
                    published_at=snippet.get("publishedAt"),
                )
                yielded += 1
                if max_comments is not None and yielded >= max_comments:
                    return

            page_token = data.get("nextPageToken")
            if not page_token:
                return

    def get_channel(self, channel: str) -> ChannelInfo:
        original_channel = channel.strip()
        channel = normalize_channel_input(original_channel)
        if original_channel.lower().startswith(("http://", "https://")) and not channel.startswith("UC"):
            channel_id = self._extract_channel_id_from_channel_page(original_channel)
            if channel_id:
                return self._get_channel_by_id(channel_id)

        if channel.startswith("UC"):
            return self._get_channel_by_id(channel)

        handle_candidates = [channel]
        if not channel.startswith("@"):
            handle_candidates.append(f"@{channel}")

        last_error: Exception | None = None
        for handle in handle_candidates:
            try:
                return self._get_channel_by_handle(handle)
            except YouTubeAPIError as exc:
                last_error = exc

        raise YouTubeAPIError(f"Channel not found for handle/id: {channel}") from last_error

    def iter_uploads_playlist(
        self,
        uploads_playlist_id: str,
        max_videos: int | None = None,
    ) -> Iterator[VideoInfo]:
        yielded = 0
        page_token: str | None = None

        while True:
            params = {
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token

            data = self._get("playlistItems", params)
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                content_details = item.get("contentDetails", {})
                video_id = content_details.get("videoId")
                if not video_id:
                    continue

                yield VideoInfo(
                    video_id=video_id,
                    title=snippet.get("title", ""),
                    channel_id=snippet.get("videoOwnerChannelId") or snippet.get("channelId", ""),
                    channel_title=snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle", ""),
                    published_at=content_details.get("videoPublishedAt") or snippet.get("publishedAt"),
                )
                yielded += 1
                if max_videos is not None and yielded >= max_videos:
                    return

            page_token = data.get("nextPageToken")
            if not page_token:
                return

    def _get_channel_by_id(self, channel_id: str) -> ChannelInfo:
        data = self._get(
            "channels",
            {
                "part": "snippet,contentDetails",
                "id": channel_id,
                "maxResults": 1,
            },
        )
        return self._channel_info_from_response(data, f"channel id {channel_id}")

    def _get_channel_by_handle(self, handle: str) -> ChannelInfo:
        data = self._get(
            "channels",
            {
                "part": "snippet,contentDetails",
                "forHandle": handle,
                "maxResults": 1,
            },
        )
        return self._channel_info_from_response(data, f"handle {handle}")

    def _channel_info_from_response(self, data: dict[str, Any], source: str) -> ChannelInfo:
        items = data.get("items", [])
        if not items:
            raise YouTubeAPIError(f"Channel not found for {source}")

        item = items[0]
        snippet = item["snippet"]
        uploads_playlist_id = (
            item.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads", "")
        )
        if not uploads_playlist_id:
            raise YouTubeAPIError(f"Uploads playlist not available for {source}")

        return ChannelInfo(
            channel_id=item["id"],
            title=snippet.get("title", ""),
            uploads_playlist_id=uploads_playlist_id,
        )

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{YOUTUBE_API_BASE}/{endpoint}"
        request_params = dict(params)
        request_params["key"] = self.api_key

        last_error: requests.RequestException | None = None
        response: requests.Response | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=request_params, timeout=self.timeout)
                break
            except requests.Timeout as exc:
                last_error = exc
            except requests.RequestException as exc:
                last_error = exc
            if attempt < self.max_retries - 1:
                time.sleep(min(2**attempt, 10))

        if response is None:
            raise YouTubeAPIError(
                f"YouTube API request timed out or failed for {endpoint} "
                f"after {self.max_retries} attempts. Last error: {last_error}"
            ) from last_error

        if response.ok:
            return response.json()

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        reason = _extract_error_reason(payload)
        message = _extract_error_message(payload) or response.text
        if reason in {"commentsDisabled", "disabledComments"}:
            raise CommentsDisabledError(message)
        if reason in {"quotaExceeded", "dailyLimitExceeded"}:
            raise QuotaExceededError(message)
        if response.status_code == 404:
            raise YouTubeAPIError(f"Resource not found: {message}")

        raise YouTubeAPIError(f"YouTube API error ({response.status_code}, {reason}): {message}")

    def _extract_channel_id_from_channel_page(self, url: str) -> str | None:
        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
        except requests.RequestException:
            return None

        patterns = (
            r'"browseId":"(UC[^"]+)"',
            r'"channelId":"(UC[^"]+)"',
            r'"externalId":"(UC[^"]+)"',
            r'<meta itemprop="channelId" content="(UC[^"]+)"',
        )
        for pattern in patterns:
            match = re.search(pattern, response.text)
            if match:
                return match.group(1)
        return None


def looks_like_song_stream_title(title: str) -> bool:
    lowered = title.casefold()
    return any(keyword.casefold() in lowered for keyword in SONG_STREAM_KEYWORDS)


def normalize_channel_input(channel: str) -> str:
    channel = channel.strip()
    if not channel.lower().startswith(("http://", "https://")):
        return channel

    parsed = urlparse(channel)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return channel

    if parts[0].startswith("@"):
        return parts[0]
    if len(parts) >= 2 and parts[0] == "channel":
        return parts[1]
    return parts[-1]


def _extract_error_reason(payload: dict[str, Any]) -> str:
    errors = payload.get("error", {}).get("errors", [])
    if errors:
        return errors[0].get("reason", "")
    return payload.get("error", {}).get("status", "")


def _extract_error_message(payload: dict[str, Any]) -> str:
    return payload.get("error", {}).get("message", "")
