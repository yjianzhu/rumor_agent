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


def _media_value(item, key: str, default: str = "") -> str:
    if isinstance(item, dict):
        return item.get(key) or default
    return getattr(item, key, default) or default


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
    Images keep their `path` and `caption` shape for template use, with `label`
    normalized to either ``"rumor"`` or ``"debunk"``: anything that is not
    explicitly ``"rumor"`` (空 label、历史 ``"evidence"``、未来未识别 label)
    一律归入 ``"debunk"``，避免老数据丢失展示。
    """
    images = []
    videos = []
    for item in media_files or []:
        media_type = _media_value(item, "type")
        if media_type == "image":
            raw_label = _media_value(item, "label")
            label = "rumor" if raw_label == "rumor" else "debunk"
            images.append({
                "path": _media_value(item, "path"),
                "caption": _media_value(item, "caption"),
                "label": label,
            })
        elif media_type == "video":
            path = _media_value(item, "path")
            videos.append({
                "url": path,
                "caption": _media_value(item, "caption"),
                "platform": detect_platform(path),
            })
    return images, videos
