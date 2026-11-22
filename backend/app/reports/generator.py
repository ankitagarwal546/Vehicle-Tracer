"""Self-contained HTML and print-ready PDF forensic reports."""
from __future__ import annotations

import base64
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import cv2
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Case

logger = logging.getLogger(__name__)
_environment = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
MAX_FRAME_WIDTH = 520


def _data_uri(relative: str | None, max_width: int | None = None) -> str | None:
    if not relative:
        return None
    path = (settings.artifact_dir / relative).resolve()
    if not path.is_relative_to(settings.artifact_dir.resolve()) or not path.exists():
        return None
    data = path.read_bytes()
    if max_width:
        image = cv2.imread(str(path))
        if image is not None and image.shape[1] > max_width:
            scale = max_width / image.shape[1]
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 78])[1].tobytes()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def build_context(case: Case) -> dict:
    clips = [{
        "camera_label": c.camera_label, "location": c.location, "filename": c.filename, "sha256": c.sha256,
        "ingested_at": _iso(c.ingested_at), "width": c.width, "height": c.height, "fps": c.fps,
        "duration_sec": c.duration_sec, "codec": c.codec,
    } for c in case.clips]
    vehicles = []
    for vehicle in sorted(case.vehicles, key=lambda v: (v.clip.camera_label, v.first_seen_sec)):
        keyframes = []
        for frame in vehicle.keyframes[:3]:
            keyframes.append({**frame, "frame_uri": _data_uri(frame.get("frame"), MAX_FRAME_WIDTH),
                              "raw_uri": _data_uri(frame.get("plate_raw")),
                              "enhanced_uri": _data_uri(frame.get("plate_enhanced"))})
        vehicles.append({
            "id": vehicle.id, "camera_label": vehicle.clip.camera_label, "track_id": vehicle.track_id,
            "first_seen_sec": vehicle.first_seen_sec, "last_seen_sec": vehicle.last_seen_sec,
            "frames_tracked": vehicle.frames_tracked, "attributes": vehicle.attributes,
            "fused_plate": vehicle.fused_plate, "keyframes": keyframes, "match": vehicle.match_result,
            "overrides": vehicle.overrides,
        })
    entities = [{"id": e.id, "fused_plate": e.fused_plate, "timeline": e.timeline, "links": e.links,
                 "match_result": e.match_result} for e in case.entities]
    audit = [{"created_at": _iso(e.created_at), "actor": e.actor, "action": e.action, "vehicle_id": e.vehicle_id,
              "field": e.field, "ai_extracted": e.ai_extracted, "investigator_verified": e.investigator_verified,
              "note": e.note} for e in case.audit_events]
    return {
        "case": case, "clips": clips, "vehicles": vehicles, "entities": entities, "audit": audit,
        "generated_at": _iso(datetime.now(timezone.utc)),
        "confident_count": sum(v["match"].get("status") == "CONFIDENT_SHORTLIST" for v in vehicles),
    }


def render_html(session: Session, case_id: str) -> str:
    case = session.get(Case, case_id)
    if case is None:
        raise KeyError(case_id)
    return _environment.get_template("report.html").render(**build_context(case))


def render_pdf(session: Session, case_id: str) -> tuple[bytes, str]:
    """Return ``(pdf_bytes, engine)``. WeasyPrint needs native libraries, so ReportLab backs it up."""
    html = render_html(session, case_id)
    try:
        from weasyprint import HTML

        return HTML(string=html).write_pdf(), "weasyprint"
    except Exception as error:  # OSError on missing Pango/Cairo, or a rendering failure.
        logger.warning("WeasyPrint unavailable, using ReportLab: %s", error)
    case = session.get(Case, case_id)
    return _reportlab_pdf(build_context(case)), "reportlab"


def _reportlab_pdf(context: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=8, leading=10)
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=7, leading=9)
    heading = ParagraphStyle("h", parent=styles["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=4)
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F8FAFC")),
                       ("VALIGN", (0, 0), (-1, -1), "TOP")])

    def p(value, style=body):
        return Paragraph(escape(str(value if value is not None else "")), style)

    def image(uri: str | None, width: float):
        if not uri:
            return p("")
        reader = io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))
        decoded = Image(reader)
        decoded.drawHeight = width * decoded.imageHeight / decoded.imageWidth
        decoded.drawWidth = width
        return decoded

    case = context["case"]
    story = [Paragraph("Vehicle Identification Forensic Report", styles["Title"]),
             p(f"Case {case.id} - {case.title} - Generated {context['generated_at']} UTC"),
             p("CONFIDENT SHORTLIST FOUND" if context["confident_count"] else "NO CONFIDENT MATCH"),
             p("Results are investigative leads and must be verified independently."),
             Paragraph("Evidence Integrity", heading)]
    rows = [[p("Camera"), p("File"), p("SHA-256"), p("Technical")]]
    rows += [[p(c["camera_label"]), p(c["filename"]), p(c["sha256"], mono),
              p(f"{c['width']}x{c['height']} {c['fps']} fps {c['duration_sec']} s {c['codec']}")]
             for c in context["clips"]]
    story.append(Table(rows, colWidths=[28 * mm, 35 * mm, 75 * mm, 40 * mm], style=grid))

    for entity in context["entities"]:
        story.append(Paragraph(f"Cross-camera entity {escape(entity['id'])}", heading))
        rows = [[p("Camera"), p("First"), p("Last"), p("Plate")]]
        rows += [[p(t["camera_label"]), p(t["first_seen_sec"]), p(t["last_seen_sec"]), p(t["plate"], mono)]
                 for t in entity["timeline"]]
        story.append(Table(rows, style=grid))
        story.append(p(f"Fused plate {entity['fused_plate'].get('text') or 'unread'}", mono))

    for vehicle in context["vehicles"]:
        match = vehicle["match"]
        story += [PageBreak(), Paragraph(f"Vehicle {escape(vehicle['id'])} - {escape(vehicle['camera_label'])}", heading),
                  p(f"{match['status']} - plate evidence {match['query_plate'] or 'unread'}", mono)]
        if vehicle["overrides"]:
            story.append(p(f"Includes investigator-verified values. AI read: {vehicle['fused_plate'].get('text') or 'unread'}"))
        pictures = [image(k.get("frame_uri"), 58 * mm) for k in vehicle["keyframes"]]
        if pictures:
            story.append(Table([pictures]))
        plates = [cell for k in vehicle["keyframes"] if k.get("raw_uri")
                  for cell in (image(k["raw_uri"], 28 * mm), image(k["enhanced_uri"], 28 * mm))]
        if plates:
            story.append(Table([plates[:6]]))
        matrix = vehicle["fused_plate"].get("matrix", [])
        if matrix:
            rows = [[p("Time")] + [p(i + 1) for i in range(len(vehicle["fused_plate"]["slots"]))]]
            rows += [[p(r["timestamp_sec"], mono)] + [p(c["char"], mono) for c in r["cells"]] for r in matrix]
            rows += [[p("Fused")] + [p(s["char"], mono) for s in vehicle["fused_plate"]["slots"]]]
            story.append(Table(rows, style=grid))
        candidates = match["candidates"] or match["rejected_candidates"]
        rows = [[p("#"), p("Plate"), p("Vehicle"), p("Status"), p("Conf.")]]
        rows += [[p(c["rank"]), p(c["vehicle"]["plate"], mono),
                  p(f"{c['vehicle']['colour']} {c['vehicle']['make']} {c['vehicle']['model']}"),
                  p(c["vehicle"]["status"]), p(f"{c['confidence']:.1f}%")] for c in candidates]
        story += [Spacer(1, 4), Table(rows, style=grid)]
        story += [p(item) for item in match["diagnostics"]]
        if candidates:
            story += [p(item) for item in candidates[0]["reasons"]]

    story += [PageBreak(), Paragraph("Investigator Audit Log", heading)]
    rows = [[p("Time"), p("Actor"), p("Action"), p("Field"), p("AI"), p("Verified")]]
    rows += [[p(e["created_at"]), p(e["actor"]), p(e["action"]), p(e["field"]), p(e["ai_extracted"], mono),
              p(e["investigator_verified"], mono)] for e in context["audit"]]
    story.append(Table(rows, style=grid))

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                      bottomMargin=14 * mm, title=f"Forensic Report {case.id}").build(story)
    return buffer.getvalue()
