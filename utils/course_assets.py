"""Unified study material assets (documents, uploaded video, external links)."""
from __future__ import annotations

import uuid
from flask import url_for

from utils.media_links import parse_media_link


VIDEO_TYPES = frozenset({"video", "youtube", "vimeo", "loom", "gdrive", "external"})
DOCUMENT_TYPES = frozenset({"pdf", "docx", "pptx", "txt", "document"})


def course_viewer_mode(material) -> str:
    """Return 'video', 'document', or 'mixed' for viewer chrome."""
    assets = assets_from_study_material(material)
    if not assets:
        return "document"
    types = {a.get("type") or "document" for a in assets}
    if types <= VIDEO_TYPES:
        return "video"
    if types & VIDEO_TYPES:
        return "mixed"
    return "document"


VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "m4v"}
DOCUMENT_EXTENSIONS = {"pdf", "pptx", "docx", "txt"}


def _asset_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else uuid.uuid4().hex[:12]


def normalize_media_assets(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [a for a in raw if isinstance(a, dict)]
    return []


def assets_from_study_material(study_material) -> list[dict]:
    """Build ordered asset list from media_assets JSON + legacy files array."""
    assets: list[dict] = []
    seen_ids: set[str] = set()

    for item in normalize_media_assets(getattr(study_material, "media_assets", None)):
        aid = str(item.get("id") or "")
        if not aid or aid in seen_ids:
            continue
        seen_ids.add(aid)
        assets.append(dict(item))

    for entry in study_material.files or []:
        if "|" not in entry:
            continue
        fid, filename = (p.strip() for p in entry.split("|", 1))
        if fid in seen_ids:
            continue
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "bin"
        if ext in VIDEO_EXTENSIONS:
            atype = "video"
        elif ext in DOCUMENT_EXTENSIONS:
            atype = ext if ext in ("pdf", "pptx", "docx", "txt") else "document"
        else:
            atype = "document"
        assets.append({
            "id": fid,
            "type": atype,
            "title": filename,
            "mongo_id": fid,
            "filename": filename,
        })
        seen_ids.add(fid)

    return assets


def viewer_assets(study_material, stream_endpoint: str) -> list[dict]:
    """Assets enriched with stream/embed URLs for the course viewer template."""
    out = []
    for a in assets_from_study_material(study_material):
        row = {
            "id": a.get("id"),
            "type": a.get("type", "document"),
            "title": a.get("title") or a.get("filename") or "Untitled",
            "content": a.get("content"),
        }
        mongo_id = a.get("mongo_id") or (
            a.get("id") if a.get("type") in ("pdf", "pptx", "docx", "txt", "video", "document") else None
        )
        if mongo_id and a.get("type") not in ("youtube", "vimeo", "gdrive", "loom", "external"):
            row["stream_url"] = stream_endpoint.replace("__FID__", str(mongo_id))
            row["mongo_id"] = str(mongo_id)
        if a.get("embed_url"):
            row["embed_url"] = a["embed_url"]
        if a.get("external_id"):
            row["external_id"] = a["external_id"]
        if a.get("url"):
            row["url"] = a["url"]
        if a.get("transcript"):
            row["transcript"] = a["transcript"]
        out.append(row)
    return out


def build_link_asset(url: str, title: str = "", transcript: str = "") -> dict | None:
    parsed = parse_media_link(url)
    if not parsed:
        return None
    label = (title or parsed.get("title_hint") or "External media").strip()
    asset = {
        "id": _asset_id("link_"),
        "type": parsed["type"],
        "title": label,
        "url": url.strip(),
        "embed_url": parsed["embed_url"],
        "external_id": parsed.get("external_id"),
    }
    if transcript.strip():
        asset["transcript"] = transcript.strip()
    return asset


def build_video_asset(mongo_id: str, filename: str, transcript: str = "") -> dict:
    asset = {
        "id": str(mongo_id),
        "type": "video",
        "title": filename,
        "mongo_id": str(mongo_id),
        "filename": filename,
    }
    if transcript.strip():
        asset["transcript"] = transcript.strip()
    return asset


def build_document_asset(mongo_id: str, filename: str) -> dict:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "document"
    doc_type = ext if ext in DOCUMENT_EXTENSIONS else "document"
    return {
        "id": str(mongo_id),
        "type": doc_type,
        "title": filename,
        "mongo_id": str(mongo_id),
        "filename": filename,
    }


def _collect_embed_meta(asset: dict, study_material) -> str:
    """Title/URL fallback text for external embed assets without transcripts."""
    lines = [
        f"[{asset.get('type', 'media').upper()}] {asset.get('title', '')}",
        asset.get("url") or asset.get("embed_url") or "",
    ]
    if study_material.description:
        lines.append(f"Course context: {study_material.description}")
    return "\n".join(line for line in lines if line).strip()


def _collect_video_fallback(asset: dict, study_material) -> str:
    """Placeholder text when an uploaded video has no transcript."""
    title = asset.get("title") or "Video"
    block = f"[VIDEO: {title}]"
    if study_material.description:
        block += f"\nCourse context: {study_material.description}"
    else:
        block += "\n(No transcript uploaded — questions will be limited.)"
    return block


def collect_ai_text(
    study_material,
    file_id: str | None = None,
    page_num: int | None = None,
) -> str:
    """Combined text for LearnIQ / exam RAG including video transcripts."""
    from study_material_routes import extract_text_from_gridfs

    tid = study_material.tenant_id
    parts: list[str] = []
    embed_types = ("youtube", "vimeo", "gdrive", "loom", "external")

    if file_id:
        asset = next(
            (a for a in assets_from_study_material(study_material) if str(a.get("id")) == str(file_id)),
            None,
        )
        if asset is not None:
            if asset.get("transcript"):
                return asset["transcript"].strip()
            if asset.get("type") in embed_types:
                return _collect_embed_meta(asset, study_material)
            mongo_id = asset.get("mongo_id") or asset.get("id")
            if mongo_id:
                text = extract_text_from_gridfs(
                    str(mongo_id),
                    page_num=page_num,
                    tenant_id=tid,
                )
                if text.strip():
                    return text.strip()
                if asset.get("type") == "video":
                    return _collect_video_fallback(asset, study_material)

    for asset in assets_from_study_material(study_material):
        t = asset.get("type") or ""
        title = asset.get("title") or "Media"
        if asset.get("transcript"):
            label = "VIDEO" if t == "video" else t.upper()
            parts.append(f"[{label}: {title}]\n{asset['transcript']}")
            continue
        if t in embed_types:
            parts.append(
                f"[{asset.get('type', 'link').upper()}: {asset.get('title', 'Media')}]\n"
                f"{asset.get('url') or asset.get('embed_url', '')}"
            )
            continue
        mongo_id = asset.get("mongo_id") or asset.get("id")
        if not mongo_id:
            continue
        if asset.get("type") == "video":
            block = f"[VIDEO: {title}]"
            if asset.get("transcript"):
                block += f"\n{asset['transcript']}"
            elif study_material.description:
                block += f"\nCourse context: {study_material.description}"
            else:
                block += "\n(No transcript uploaded — questions will be limited.)"
            parts.append(block)
            continue
        text = extract_text_from_gridfs(str(mongo_id), tenant_id=tid)
        if text.strip():
            parts.append(text)

    if not parts and study_material.description:
        parts.append(study_material.description)

    return "\n\n".join(parts).strip()


def course_picker_row(material) -> dict:
    """Dict for exam admin/create course dropdowns."""
    return {
        "id": material.id,
        "title": material.title,
        "level_number": material.level.level_number if material.level else (material.minimum_level or 1),
        "category_id": material.category_id,
        "category_name": material.category.name if material.category else "General",
        "media_summary": course_media_summary(material),
    }


def course_media_summary(material) -> str:
    """Short label for exam AI source picker (docs / video / links)."""
    assets = assets_from_study_material(material)
    if not assets:
        return "no content"
    tags: list[str] = []
    for a in assets:
        t = a.get("type") or ""
        if t in ("pdf", "docx", "pptx", "txt", "document") and "docs" not in tags:
            tags.append("docs")
        elif t == "video":
            if a.get("transcript") and "video+transcript" not in tags:
                tags.append("video+transcript")
            elif "video" not in tags and "video+transcript" not in tags:
                tags.append("video")
        elif t in ("youtube", "vimeo", "gdrive", "loom", "external"):
            if a.get("transcript") and "video+transcript" not in tags:
                tags.append("video+transcript")
            elif "links" not in tags and "video+transcript" not in tags:
                tags.append("links")
    return " · ".join(tags) if tags else "content"
