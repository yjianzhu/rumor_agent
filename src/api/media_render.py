from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class VideoPlatform:
    key: str           # bilibili / youtube / douyin / xiaohongshu / weibo / generic
    label: str         # 显示名
    accent: str        # tailwind 色 (rose / fuchsia / red / neutral / amber / sky)


_PLATFORMS: tuple[tuple[tuple[str, ...], VideoPlatform], ...] = (
    (("bilibili.com", "b23.tv"), VideoPlatform("bilibili", "Bilibili", "fuchsia")),
    (("youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"),
        VideoPlatform("youtube", "YouTube", "red")),
    (("douyin.com", "www.douyin.com", "v.douyin.com"),
        VideoPlatform("douyin", "抖音", "neutral")),
    (("xiaohongshu.com", "www.xiaohongshu.com", "xhslink.com"),
        VideoPlatform("xiaohongshu", "小红书", "rose")),
    (("weibo.com", "www.weibo.com", "weibo.cn", "video.weibo.com"),
        VideoPlatform("weibo", "微博", "amber")),
)

_GENERIC = VideoPlatform("generic", "外部链接", "sky")


def detect_platform(url: str) -> VideoPlatform:
    """Map a video URL to its platform metadata."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return _GENERIC
    if not host:
        return _GENERIC
    for hosts, platform in _PLATFORMS:
        if host in hosts:
            return platform
    # 兜底：覆盖二级域名 / mobile 子域
    for hosts, platform in _PLATFORMS:
        if any(host.endswith("." + h) for h in hosts):
            return platform
    return _GENERIC


def split_media(media_files):
    """Split a list of MediaItem-like objects into (images, videos).

    Each video item is augmented to a dict with `url`, `caption`, `platform`.
    Images keep their `path` and `caption` shape for template use.
    """
    images = []
    videos = []
    for item in media_files or []:
        if item.type == "image":
            images.append(item)
        elif item.type == "video":
            videos.append({
                "url": item.path,
                "caption": item.caption,
                "platform": detect_platform(item.path),
            })
    return images, videos
