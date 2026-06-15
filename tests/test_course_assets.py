"""Tests for course asset helpers."""
from unittest.mock import patch

from utils.course_assets import (
    assets_from_study_material,
    build_link_asset,
    build_video_asset,
    build_document_asset,
    collect_ai_text,
    course_media_summary,
    course_viewer_mode,
)
from utils.course_edit import sync_files_from_media_assets


class _Material:
    def __init__(self, files=None, media_assets=None, description="", tenant_id=1):
        self.files = files or []
        self.media_assets = media_assets or []
        self.description = description
        self.tenant_id = tenant_id


def test_assets_from_legacy_files_only():
    m = _Material(files=["mongo123|guide.pdf"])
    assets = assets_from_study_material(m)
    assert len(assets) == 1
    assert assets[0]["type"] == "pdf"
    assert assets[0]["id"] == "mongo123"


def test_assets_merge_media_assets_and_files_without_duplicates():
    m = _Material(
        files=["mongo123|guide.pdf"],
        media_assets=[build_document_asset("mongo123", "guide.pdf")],
    )
    assets = assets_from_study_material(m)
    assert len(assets) == 1


def test_build_link_asset_youtube():
    asset = build_link_asset("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Demo")
    assert asset is not None
    assert asset["type"] == "youtube"
    assert asset["title"] == "Demo"


def test_build_link_asset_with_transcript():
    asset = build_link_asset(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "Demo",
        "Transcript text here",
    )
    assert asset["transcript"] == "Transcript text here"


def test_course_viewer_mode_video_only():
    m = _Material(
        media_assets=[
            build_link_asset("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "A"),
        ]
    )
    assert course_viewer_mode(m) == "video"


def test_build_video_asset_with_transcript():
    asset = build_video_asset("vid1", "lesson.mp4", "Hello world transcript")
    assert asset["transcript"] == "Hello world transcript"
    assert asset["type"] == "video"


def test_sync_files_from_media_assets():
    assets = [
        build_document_asset("abc", "doc.pdf"),
        build_video_asset("vid", "a.mp4"),
        build_link_asset("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "YT"),
    ]
    files = sync_files_from_media_assets(assets)
    assert len(files) == 2  # link has no mongo id
    assert any("abc|doc.pdf" in f for f in files)


def test_collect_ai_text_returns_transcript_for_file_id():
    m = _Material(
        media_assets=[build_video_asset("v1", "lesson.mp4", "Spoken content here")],
    )
    text = collect_ai_text(m, file_id="v1")
    assert text == "Spoken content here"


def test_collect_ai_text_invalid_file_id_falls_through():
    m = _Material(
        media_assets=[build_video_asset("v1", "lesson.mp4", "Transcript")],
    )
    text = collect_ai_text(m, file_id="missing")
    assert "Transcript" in text


def test_collect_ai_text_youtube_without_transcript():
    m = _Material(
        media_assets=[build_link_asset("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Intro")],
        description="Course overview",
    )
    asset_id = m.media_assets[0]["id"]
    text = collect_ai_text(m, file_id=asset_id)
    assert "[YOUTUBE]" in text.upper()
    assert "Intro" in text
    assert "Course overview" in text


@patch("study_material_routes.extract_text_from_gridfs", return_value="Page one text")
def test_collect_ai_text_pdf_passes_page_num(mock_extract):
    m = _Material(media_assets=[build_document_asset("doc1", "guide.pdf")])
    text = collect_ai_text(m, file_id="doc1", page_num=2)
    assert text == "Page one text"
    mock_extract.assert_called_once_with("doc1", page_num=2, tenant_id=1)


def test_course_media_summary_embed_with_transcript():
    m = _Material(
        media_assets=[
            build_link_asset(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "Lecture",
                "Full lecture transcript",
            )
        ],
    )
    assert course_media_summary(m) == "video+transcript"


def test_ai_cache_make_key_accepts_video_context():
    from utils.ai_cache import make_key

    key = make_key("summarize", 1, "f1", 2, "youtube", 100, "gemma4:e4b")
    assert len(key) == 64
