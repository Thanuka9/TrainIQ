"""Parse external video/document links for study material assets."""
import re
from urllib.parse import parse_qs, urlparse

# CSP frame-src hosts — keep in sync with parse_media_link() providers
EMBED_FRAME_CSP = (
    "'self'",
    "https://www.youtube-nocookie.com",
    "https://www.youtube.com",
    "https://player.vimeo.com",
    "https://drive.google.com",
    "https://docs.google.com",
    "https://www.loom.com",
    "https://*.sharepoint.com",
    "https://*.sharepoint.de",
    "https://onedrive.live.com",
    "https://www.dropbox.com",
    "https://stream.microsoft.com",
)


def _clean_url(url: str) -> str:
    return (url or "").strip()


def parse_media_link(url: str) -> dict | None:
    """
    Detect provider and return asset fields: type, title_hint, embed_url, external_id.
    Returns None if URL is not recognized.
    """
    url = _clean_url(url)
    if not url:
        return None

    lower = url.lower()

    # YouTube
    yt_id = _youtube_id(url)
    if yt_id:
        return {
            "type": "youtube",
            "external_id": yt_id,
            "embed_url": f"https://www.youtube-nocookie.com/embed/{yt_id}",
            "title_hint": f"YouTube video {yt_id}",
        }

    # Vimeo
    vm = re.search(r"vimeo\.com/(?:video/)?(\d+)", lower)
    if vm:
        vid = vm.group(1)
        return {
            "type": "vimeo",
            "external_id": vid,
            "embed_url": f"https://player.vimeo.com/video/{vid}",
            "title_hint": f"Vimeo video {vid}",
        }

    # Google Drive file
    gd = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", url)
    if gd:
        fid = gd.group(1)
        return {
            "type": "gdrive",
            "external_id": fid,
            "embed_url": f"https://drive.google.com/file/d/{fid}/preview",
            "title_hint": f"Google Drive file {fid[:8]}…",
        }

    # Google Drive open?id=
    gd2 = re.search(r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)", url)
    if gd2:
        fid = gd2.group(1)
        return {
            "type": "gdrive",
            "external_id": fid,
            "embed_url": f"https://drive.google.com/file/d/{fid}/preview",
            "title_hint": f"Google Drive file {fid[:8]}…",
        }

    # Loom
    loom = re.search(r"loom\.com/share/([a-zA-Z0-9]+)", lower)
    if loom:
        lid = loom.group(1)
        return {
            "type": "loom",
            "external_id": lid,
            "embed_url": f"https://www.loom.com/embed/{lid}",
            "title_hint": f"Loom recording {lid[:8]}…",
        }

    # Known embed hosts only (no arbitrary URL iframes)
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None
    host = (parsed.netloc or "").lower()
    allowed_suffixes = (
        "sharepoint.com",
        "sharepoint.de",
        "onedrive.live.com",
        "1drv.ms",
        "docs.google.com",
        "dropbox.com",
        "stream.microsoft.com",
    )
    if any(host == s or host.endswith("." + s) for s in allowed_suffixes):
        return {
            "type": "external",
            "external_id": url,
            "embed_url": url,
            "title_hint": "External link",
        }

    return None


def _youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().replace("www.", "")

    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
        return vid if re.fullmatch(r"[\w-]{11}", vid) else None

    if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            q = parse_qs(parsed.query).get("v", [None])[0]
            return q if q and re.fullmatch(r"[\w-]{11}", q) else None
        m = re.match(r"^/(embed|shorts|live)/([\w-]{11})", parsed.path)
        if m:
            return m.group(2)

    return None
