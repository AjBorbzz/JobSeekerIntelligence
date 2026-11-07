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

    def fields(values: dict, depth: int = 0):
        style = ParagraphStyle(
            f"depth{depth}", parent=body, leftIndent=min(depth, 3) * 12,
        )
        for key, value in values.items():
            label = key.replace("_", " ").capitalize()
            if isinstance(value, dict):
                paragraph(label, heading if depth == 0 else style)
                fields(value, depth + 1)
            elif isinstance(value, list):
                list_heading = ParagraphStyle(f"list{depth}", parent=style, fontName=BOLD, keepWithNext=True)
                paragraph(label, list_heading)
                if not value:
                    paragraph("None recorded", style)
                for index, item in enumerate(value, 1):
                    if isinstance(item, dict):
                        paragraph(f"{label} item {index}", style)
                        fields(item, depth + 1)
                    else:
                        paragraph("- " + str(item), style)
            else:
                paragraph("Not supplied" if value is None else value, style, label=label)

    def section(name: str):
        paragraph(name, heading)

    paragraph("JOB INTELLIGENCE", small)
    paragraph("Job Intelligence Report", title)
    paragraph(report.job.title, heading)
    paragraph("Saved-data export | AI-generated content requires human review.", small)
    paragraph("Generated at " + report.generated_at.isoformat(), small)
    paragraph("Job " + str(report.job.id), small)
    story.append(Spacer(1, 8))
    job_score = f"{report.proposal.job_relevance_score:.2f} / 100" if report.proposal else "Not recorded"
    poc_score = f"{report.evaluation.poc_relevance_score:.2f} / 100" if report.evaluation else "Not evaluated"
    scores = Table([
        [Paragraph("Job relevance at proposal generation", small), Paragraph("POC relevance for selected proposal", small)],
        [Paragraph(job_score, heading), Paragraph(poc_score, heading)],
    ], colWidths=[245, 245])
    scores.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EAF3F4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.5, TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))

    story.append(scores)
    section("1. Job facts and source notes")
    fields(report.job.model_dump(mode="json", exclude={"id"}))
    section("2. Saved search criteria")
    fields(report.request.model_dump(mode="json")) if report.request else paragraph("No saved proposal request.")
    section("3. Analysis")
    paragraph("Analysis source: " + report.analysis_origin, small)
    fields(report.analysis.model_dump(mode="json", exclude={"job_id"})) if report.analysis else paragraph("No saved analysis.")
    section("4. POC proposal")
    fields(report.proposal.model_dump(mode="json", exclude={"job_id"})) if report.proposal else paragraph("No saved proposal.")
    section("5. Linked POC evaluation")
    fields(report.evaluation.model_dump(mode="json", exclude={"job_id"})) if report.evaluation else paragraph(
        "No saved evaluation for the selected proposal." if report.proposal else "No proposal selected; no evaluation attached."
    )
    section("6. Provenance and limitations")
    fields({
        "report_layout_version": 1,
        "proposal_id": report.proposal_id,
        "proposal_saved_at": report.proposal_saved_at.isoformat() if report.proposal_saved_at else None,
        "evaluation_id": report.evaluation_id,
        "evaluation_saved_at": report.evaluation_saved_at.isoformat() if report.evaluation_saved_at else None,
        "latest_analysis_saved_at": str(report.latest_analysis_saved_at) if report.latest_analysis_saved_at else None,
    })
    for note in (
        "Job facts are the current stored job row, not a reconstructed historical advertisement.",
        "When a proposal is selected, its saved analysis and request are used; only its linked evaluation is attached.",
        "The job score is the value saved in the proposal. Independent semantic/hybrid history is not joined without exact input linkage.",
        "Requirement IDs are displayed as stored. Consult the saved analysis; no missing requirement text is invented.",
        "Scores are not hiring probabilities. This export does not verify that a vacancy remains open or that AI interpretation is correct.",
        "No model, embedding, website, external image, or external font is called during export.",
        "Display policy: peso becomes PHP; unsupported font characters appear as [U+XXXX]; controls are removed and dashes normalized.",
        "This is not a signed audit record, a complete model/prompt reproduction package, an encrypted PDF, or a redacted public portfolio copy.",
    ):
        paragraph(note, small)

    def furniture(canvas, doc):
        if doc.page > MAX_PAGES:
            raise ReportTooLarge("Report exceeds the configured page limit")
        canvas.saveState()
        canvas.setStrokeColor(TEAL)
        canvas.line(48, A4[1] - 38, A4[0] - 48, A4[1] - 38)
        canvas.setFont(FONT, 8)
        canvas.setFillColor(NAVY)
        canvas.drawString(48, 27, "Job Intelligence | Saved-data export")
        canvas.drawRightString(A4[0] - 48, 27, f"Page {doc.page}")
        canvas.restoreState()

    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=48, rightMargin=48, topMargin=50, bottomMargin=46,
        title="Job Intelligence Report", author="Job Intelligence", pageCompression=1,
    )
    document.build(story, onFirstPage=furniture, onLaterPages=furniture)
    data = output.getvalue()
    if len(data) > MAX_PDF_BYTES:
        raise ReportTooLarge("PDF exceeds the configured output limit")
    return data