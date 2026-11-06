"""Checks how many pages a Word file needs. A rendered check is the only real proof."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Estimation numbers for Helvetica/Arial 12 pt on A4 with 2 cm margins (deliberately cautious).
CHARS_PER_LINE = 80
LINE_HEIGHT_PT = 13.8
PAGE_TEXT_HEIGHT_PT = 25.7 / 2.54 * 72  # 29.7 cm page minus 2 x 2 cm margins


def find_soffice():
    """Find LibreOffice, a free program that can open Word files and print them to PDF."""
    configured = os.environ.get("LIBREOFFICE_PATH", "").strip()
    candidates = [configured, shutil.which("soffice"), shutil.which("libreoffice"),
                  r"C:\Program Files\LibreOffice\program\soffice.exe",
                  r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                  "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def count_pages_with_libreoffice(docx_bytes):
    """Real rendering: convert to PDF and count its pages. Returns None if that was not possible."""
    soffice = find_soffice()
    if not soffice:
        return None
    try:
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "check.docx"
            src.write_bytes(docx_bytes)
            profile = (Path(tmp) / "profile").resolve().as_uri()
            subprocess.run(
                [soffice, f"-env:UserInstallation={profile}", "--headless",
                 "--convert-to", "pdf", "--outdir", tmp, str(src)],
                check=True, capture_output=True, timeout=120)
            pdf = Path(tmp) / "check.pdf"
            if not pdf.exists():
                return None
            return len(PdfReader(str(pdf)).pages)
    except Exception:
        return None


def estimate_pages(name_line, class_line, body):
    """A rough calculation, NOT a rendering. Used only when LibreOffice is not available."""
    paragraphs = [name_line, class_line] + [p for p in (body or "").replace("\r\n", "\n").split("\n\n") if p.strip()]
    lines = sum(max(1, -(-len(" ".join(p.split())) // CHARS_PER_LINE)) for p in paragraphs)
    height = lines * LINE_HEIGHT_PT + len(paragraphs) * 4
    return 1 if height <= PAGE_TEXT_HEIGHT_PT else 2


def check_pages(docx_bytes, name_line, class_line, body):
    """Returns {"count": int|None, "status": ..., "note": text}."""
    counted = count_pages_with_libreoffice(docx_bytes)
    if counted is not None:
        if counted == 1:
            return {"count": 1, "status": "ok",
                    "note": "Rendered with LibreOffice: 1 page. Helvetica may be replaced by a similar font, "
                            "so also open the file in Word to confirm."}
        return {"count": counted, "status": "too_long",
                "note": f"Rendered with LibreOffice: {counted} pages. The report does not fit on one page. "
                        "Shorten the text; never shrink the font or margins."}
    est = estimate_pages(name_line, class_line, body)
    if est == 1:
        return {"count": None, "status": "estimated_ok",
                "note": "Estimate only (no page renderer found): it should fit on one page. "
                        "Open the file in Word to confirm."}
    return {"count": None, "status": "estimated_long",
            "note": "Estimate only (no page renderer found): the text may run onto a second page. "
                    "Open the file in Word to check, and shorten the text if needed."}
