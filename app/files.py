"""Safe handling of uploaded report files."""
import io
import os
import re
import uuid
import zipfile
from flask import current_app

MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # protection against "zip bombs"
STORED_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(docx|pdf)$")
MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


class UploadError(Exception):
    """Message is safe to show to the user."""


def inspect_upload(data, ext):
    """Check the real content of the file. Returns (file_type, extracted_text)."""
    if not data:
        raise UploadError("The file is empty.")
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            raise UploadError("This does not look like a real PDF file.")
        return "pdf", None
    if ext == "docx":
        return "docx", _read_docx(data)
    raise UploadError("Only .docx (Word) and .pdf files are allowed.")


def _read_docx(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if "word/document.xml" not in names:
                raise UploadError("This does not look like a Word .docx file. "
                                  "(Old .doc files must be re-saved as .docx first.)")
            if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise UploadError("This file is unusually large inside. It was not accepted.")
    except zipfile.BadZipFile:
        raise UploadError("This does not look like a Word .docx file.")

    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception:
        raise UploadError("The Word file could not be read. Is it damaged or password-protected?")


def _folder():
    return os.path.join(current_app.config["UPLOAD_FOLDER"], "historical")


def save_bytes(data, file_type):
    """Store the file under a random server-made name. Returns that name."""
    os.makedirs(_folder(), exist_ok=True)
    name = f"{uuid.uuid4().hex}.{file_type}"
    with open(os.path.join(_folder(), name), "xb") as f:
        f.write(data)
    return name


def stored_path(name):
    """Full path for a stored name. Refuses anything that is not a server-made name."""
    if not STORED_NAME_RE.match(name or ""):
        raise ValueError("Invalid stored file name")
    return os.path.join(_folder(), name)
