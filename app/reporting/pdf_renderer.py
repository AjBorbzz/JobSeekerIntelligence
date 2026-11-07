from io import BytesIO
from pathlib import Path
from threading import Lock
from unicodedata import category
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


from app.models.report import ReportSnapshot, ReportTooLarge

MAX_PAGES = 100
MAX_PDF_BYTES = 8_000_000
_RENDER_LOCK = Lock()
FONT = "JI-Vera"
BOLD = "JI-Vera-Bold"
NAVY = colors.HexColor("#17364A")
TEAL = colors.HexColor("#087F8C")

def ensure_fonts() -> None:
    if FONT not in pdfmetrics.getRegisteredFontNames():
        directory = Path(reportlab.__file__).resolve().parent / "fonts"
        pdfmetrics.registerFont(TTFont(FONT, str(directory / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont(BOLD, str(directory / "VeraBd.ttf")))
        pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=BOLD, italic=FONT, boldItalic=BOLD)

def display_text(value) -> str:
    text = str(value).replace("₱", "PHP ")
    for mark in ("–", "—", "‑"):
        text = text.replace(mark, "-")

    glyphs = pdfmetrics.getFont(FONT).face.charToGlyph
    return "".join(" " if category(char).startswith("C")
                   else char if ord(char) in glyphs else 
                   f"[U+{ord(char):04X}]" for char in text)


def render_pdf(report: ReportSnapshot) -> bytes:
    with _RENDER_LOCK:
        ensure_fonts()
        return _render(report)

def _render(report: ReportSnapshot) -> bytes:
    output = BytesIO()
    body = ParagraphStyle(
        "body", fontName=FONT, fontsize=9, leading=13, textColor=NAVY,
        spaceAfter=5, alignment=TA_LEFT, splitLongWords=True,
    )
    heading = ParagraphStyle(
        "heading", parent=body, fontName=BOLD, fontSize=13, leading=17,
        textColor=TEAL, spaceBefore=16, spaceAfter=8, keepWithNext=True,
    )
    title = ParagraphStyle("title", parent=heading, fontSize=23, leading=28, textColor=NAVY)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=11)
    story = []

    def paragraph(value, style=body, label: str | None = None):
        text = display_text(value)
        # Keep each flowable reasonably sized; no content is silently truncated.
        while text:
            end = len(text) if len(text) <= 1600 else max(text.rfind(" ", 0, 1600), 800)
            prefix = f"<b>{escape(display_text(label))}:</b> " if label is not None else ""
            story.append(Paragraph(prefix + escape(text[:end]), style))
            label = None
            text = text[end:]
        if not str(value):
            story.append(Paragraph("Not supplied", style))