"""Tests for media link parsing."""
import pytest

from utils.media_links import parse_media_link, _youtube_id


@pytest.mark.parametrize(
    "url,expected_type",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
        ("https://vimeo.com/123456789", "vimeo"),
        ("https://drive.google.com/file/d/abc123XYZ/view", "gdrive"),
        ("https://www.loom.com/share/abc123def456", "loom"),
        ("https://contoso.sharepoint.com/sites/training/video.mp4", "external"),
    ],
)
def test_parse_media_link_supported(url, expected_type):
    result = parse_media_link(url)
    assert result is not None
    assert result["type"] == expected_type
    assert result["embed_url"].startswith("https://")


def test_parse_media_link_rejects_javascript():
    assert parse_media_link("javascript:alert(1)") is None


def test_parse_media_link_rejects_random_http():
    assert parse_media_link("http://evil.example.com/phish") is None


def test_youtube_id_variants():
    assert _youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert _youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
