"""Admin course edit — media_assets CRUD helpers."""
from __future__ import annotations

import logging

from bson.objectid import ObjectId
from werkzeug.utils import secure_filename

from utils.course_assets import (
    assets_from_study_material,
    build_document_asset,
    build_link_asset,
    build_video_asset,
)
from utils.media_upload_constants import allowed_document, allowed_video
from utils.mongo_tenant import get_tenant_gridfs

logger = logging.getLogger(__name__)


def sync_files_from_media_assets(media_assets: list[dict]) -> list[str]:
    """Keep legacy files[] in sync with GridFS-backed assets."""
    out = []
    for a in media_assets:
        mongo_id = a.get("mongo_id") or (
            a.get("id") if a.get("type") in ("pdf", "docx", "pptx", "txt", "video", "document") else None
        )
        if not mongo_id:
            continue
        fname = a.get("filename") or a.get("title") or str(mongo_id)
        out.append(f"{mongo_id}|{fname}")
    return out


def apply_course_media_edits(course, form, files) -> None:
    """
    Mutate course.media_assets and course.files from admin edit_course POST.
    """
    from utils.course_assets import assets_from_study_material

    assets = assets_from_study_material(course)
    delete_ids = set(form.getlist("delete_assets"))
    gfs = get_tenant_gridfs(course.tenant_id)

    kept: list[dict] = []
    for a in assets:
        aid = str(a.get("id", ""))
        if aid in delete_ids:
            mongo_id = a.get("mongo_id")
            if mongo_id:
                try:
                    gfs.delete(ObjectId(str(mongo_id)))
                except Exception as e:
                    logger.warning("GridFS delete failed %s: %s", mongo_id, e)
            continue
        transcript_key = f"asset_transcript_{aid}"
        if transcript_key in form:
            text = (form.get(transcript_key) or "").strip()
            if text:
                a["transcript"] = text
            elif "transcript" in a:
                del a["transcript"]
        kept.append(a)

    # New documents
    for doc in files.getlist("new_files"):
        if not (doc and doc.filename and allowed_document(doc.filename)):
            continue
        fn = secure_filename(doc.filename)
        mongo_id = gfs.put(
            doc.read(),
            filename=fn,
            metadata={"tenant_id": course.tenant_id, "study_material_id": course.id, "asset_type": "document"},
        )
        kept.append(build_document_asset(str(mongo_id), fn))

    # New videos + per-file transcripts
    new_videos = files.getlist("new_videos")
    transcripts = form.getlist("new_video_transcripts")
    for idx, vid in enumerate(new_videos):
        if not (vid and vid.filename and allowed_video(vid.filename)):
            continue
        fn = secure_filename(vid.filename)
        mongo_id = gfs.put(
            vid.read(),
            filename=fn,
            metadata={"tenant_id": course.tenant_id, "study_material_id": course.id, "asset_type": "video"},
        )
        transcript = transcripts[idx].strip() if idx < len(transcripts) else ""
        kept.append(build_video_asset(str(mongo_id), fn, transcript))

    # New external links
    link_urls = form.getlist("new_link_urls")
    link_titles = form.getlist("new_link_titles")
    link_transcripts = form.getlist("new_link_transcripts")
    for idx, raw_url in enumerate(link_urls):
        url = (raw_url or "").strip()
        if not url:
            continue
        title = (link_titles[idx] if idx < len(link_titles) else "").strip()
        transcript = (link_transcripts[idx] if idx < len(link_transcripts) else "").strip()
        asset = build_link_asset(url, title, transcript)
        if asset:
            kept.append(asset)

    course.media_assets = kept
    course.files = sync_files_from_media_assets(kept)

    # Legacy delete_files / replace still handled in edit_course for backward compat;
    # remove deleted mongo ids from media_assets if legacy path deleted them
    legacy_deleted = set(form.getlist("delete_files"))
    if legacy_deleted:
        course.media_assets = [
            a for a in course.media_assets
            if str(a.get("mongo_id") or "") not in legacy_deleted and str(a.get("id") or "") not in legacy_deleted
        ]
        course.files = sync_files_from_media_assets(course.media_assets)

    # Recompute total_pages rough estimate
    total = 0
    for a in course.media_assets:
        t = a.get("type", "")
        if t == "pdf":
            total += max(a.get("page_count") or 1, 1)
        else:
            total += 1
    course.total_pages = max(total, 1)


def course_assets_for_template(course) -> list[dict]:
    """Assets for admin template display."""
    return assets_from_study_material(course)