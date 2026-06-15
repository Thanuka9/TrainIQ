"""SCORM 1.2 / 2004 and xAPI package import helpers (foundation)."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

SCORM_MANIFEST = "imsmanifest.xml"
XAPI_EXTENSIONS = {".json", ".xml"}


@dataclass
class ScormPackageInfo:
    title: str
    version: str
    launch_href: str | None
    identifier: str | None
    format: str  # scorm12 | scorm2004 | xapi | unknown


def _text(el, default=""):
    if el is None:
        return default
    return (el.text or default).strip()


def parse_scorm_manifest(manifest_xml: str) -> ScormPackageInfo:
    """Parse imsmanifest.xml from a SCORM package."""
    root = ElementTree.fromstring(manifest_xml)
    ns = {"imscp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2"}
    title_el = root.find(".//imscp:title", ns) or root.find(".//{*}title")
    resource = root.find(".//{*}resource[@href]")
    schema = _text(root.find(".//{*}schema"))
    schemaversion = _text(root.find(".//{*}schemaversion"))
    version = schemaversion or schema or "1.2"
    return ScormPackageInfo(
        title=_text(title_el, "Imported SCORM course"),
        version=version,
        launch_href=resource.get("href") if resource is not None else None,
        identifier=root.get("identifier"),
        format="scorm2004" if "2004" in version else "scorm12",
    )


def detect_xapi_package(extract_dir: str) -> ScormPackageInfo | None:
    """Detect Tin Can / xAPI JSON launch descriptors."""
    for name in os.listdir(extract_dir):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(extract_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and ("launch" in data or "activities" in data):
            return ScormPackageInfo(
                title=data.get("name") or data.get("title") or name,
                version="xAPI",
                launch_href=data.get("launch"),
                identifier=data.get("id"),
                format="xapi",
            )
    return None


def inspect_scorm_zip(zip_path: str) -> ScormPackageInfo:
    """Extract and inspect a SCORM/xAPI zip upload."""
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)
        manifest_path = os.path.join(tmp, SCORM_MANIFEST)
        if os.path.isfile(manifest_path):
            with open(manifest_path, encoding="utf-8", errors="replace") as fh:
                return parse_scorm_manifest(fh.read())
        xapi = detect_xapi_package(tmp)
        if xapi:
            return xapi
    return ScormPackageInfo(
        title="Unknown package",
        version="unknown",
        launch_href=None,
        identifier=None,
        format="unknown",
    )


def import_scorm_to_course(zip_path: str, *, tenant_id: int, title_override: str | None = None):
    """
    Create a StudyMaterial stub from a SCORM/xAPI zip.
    Full runtime player integration is a future phase — metadata stored in media_assets.
    """
    from extensions import db
    from models import StudyMaterial

    info = inspect_scorm_zip(zip_path)
    title = (title_override or info.title)[:255]
    material = StudyMaterial(
        title=title,
        description=f"Imported {info.format.upper()} package (v{info.version})",
        course_time=60,
        max_time=120,
        total_pages=1,
        files=[],
        media_assets=[{
            "id": f"scorm-{info.identifier or 'import'}",
            "type": "scorm",
            "format": info.format,
            "version": info.version,
            "launch_href": info.launch_href,
            "identifier": info.identifier,
        }],
        minimum_level=1,
        tenant_id=tenant_id,
    )
    db.session.add(material)
    db.session.commit()
    logger.info("SCORM import stub created: %s (%s)", material.id, info.format)
    return material, info
