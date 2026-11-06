"""Builds the sponsor-report Word file with python-docx (never by asking the AI to format it)."""
import io
import re
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_LINE_SPACING, WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

FONT = "Helvetica"
FONT_SIZE = Pt(12)
SPACE_AFTER = Pt(4)


def _force_font(rpr_owner):
    """Write the font name into every Word font slot (and drop theme fonts that would override it)."""
    rpr = rpr_owner.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), FONT)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        if rfonts.get(qn(attr)) is not None:
            del rfonts.attrib[qn(attr)]


def body_paragraphs(body):
    """Blank line = new paragraph. A single line break inside a paragraph becomes a space."""
    parts = re.split(r"\n\s*\n", (body or "").replace("\r\n", "\n"))
    return [" ".join(p.split()) for p in parts if p.strip()]


def build_docx(name_line, class_line, body):
    """Returns the .docx file as bytes: A4 portrait, 2 cm margins, Helvetica 12 pt,
    single spacing, 4 pt after paragraphs, two identification lines then the body."""
    doc = Document()

    section = doc.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2)
    section.header_distance = section.footer_distance = Cm(1)
    section.gutter = Cm(0)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = FONT_SIZE
    _force_font(normal.element)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = SPACE_AFTER
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE

    doc.core_properties.author = "Happy Children Nepal"
    doc.core_properties.title = ""

    lines = [name_line.strip(), class_line.strip()] + body_paragraphs(body)
    for text in lines:
        if not text:
            continue  # never an empty paragraph
        p = doc.add_paragraph()
        fmt = p.paragraph_format
        fmt.space_before = Pt(0)
        fmt.space_after = SPACE_AFTER
        fmt.line_spacing_rule = WD_LINE_SPACING.SINGLE
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        run = p.add_run(text)
        run.font.name = FONT
        run.font.size = FONT_SIZE
        _force_font(run._r)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _clean(part):
    return re.sub(r"[^A-Za-z0-9\-]", "", part or "")


def _initials(last_name):
    words = re.split(r"[\s\-]+", (last_name or "").strip())
    return "".join(w[0].upper() for w in words if w[:1].isalnum())


def report_filename(child, all_children):
    """[FirstName]_Report.docx. Initials (of the surname) are added ONLY when another child has
    the same first name. If even the initials clash, the child ID is added so nothing is overwritten."""
    first = _clean(child.first_name) or "Child"
    same_first = [c for c in all_children
                  if c.id != child.id and c.first_name.strip().lower() == child.first_name.strip().lower()]
    if not same_first:
        return f"{first}_Report.docx"
    initials = _initials(child.last_name) or "X"
    name = f"{first}_{initials}"
    if any(_initials(c.last_name) == initials for c in same_first):
        name += f"-{child.id}"
    return f"{name}_Report.docx"
