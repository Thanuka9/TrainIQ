"""Shared upload limits and extension checks for study materials."""

ALLOWED_DOC_EXTENSIONS = {"pptx", "pdf", "docx", "txt"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "m4v"}
MAX_DOC_SIZE_MB = 100
MAX_VIDEO_SIZE_MB = 500


def allowed_document(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_DOC_EXTENSIONS


def allowed_video(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS
