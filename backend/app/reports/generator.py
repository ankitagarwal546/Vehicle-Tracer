"""Scannable HTML and PDF forensic reports with an optional detailed appendix."""
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

from app.api.labels import ENTITY_STATUS_LABELS, EVIDENCE_TIER_LABELS, OUTCOME_LABELS, PLATE_FORMAT_LABELS, pretty
from app.config import settings
from app.db.models import Case
from app.services.case_summary import headline, readability, summarise
from app.services.pipeline_orchestrator import load_registry

logger = logging.getLogger(__name__)
_environment = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)
_environment.filters["pretty"] = pretty
MAX_CROP_WIDTH = 420
MAX_KEY_VEHICLES = 8
MAX_NO_MATCH_ROWS = 8
MAX_AUDIT_ROWS = 8
MAX_OCR_EXAMPLES = 4
MAX_COVERAGE_ROWS = 12
OUTCOME_ORDER = {"PLATE_CANDIDATE": 0, "AMBIGUOUS": 1}


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


def _attribute_line(attributes: dict) -> str:
    colours = attributes.get("colours") or []
    colour = colours[0]["label"] if colours else "colour unknown"
    body = pretty((attributes.get("body_type") or {}).get("label", "body unknown"))
    predictions = (attributes.get("make_model") or {}).get("predictions") or []
    model = "model unknown"
    if predictions and predictions[0]["make"] != "Unknown":
        model = f"estimated {predictions[0]['make']} {predictions[0]['model']}"
    return f"{colour}, {body}, {model}"


def build_context(session: Session, case: Case, appendix: bool, clip_id: str | None = None) -> dict:
    scoped_clips = [c for c in case.clips if clip_id is None or c.id == clip_id]
    scoped_vehicles = [v for v in case.completed_vehicles if clip_id is None or v.clip_id == clip_id]
    clips = [{
        "camera_label": c.camera_label, "location": c.location, "filename": c.filename, "sha256": c.sha256,
        "ingested_at": _iso(c.ingested_at), "recorded_at": _iso(c.recorded_at), "width": c.width, "height": c.height,
        "fps": c.fps, "duration_sec": c.duration_sec, "codec": c.codec, "plate_script": c.plate_script,
        "plate_format": PLATE_FORMAT_LABELS.get(c.plate_format, c.plate_format), "timezone": c.timezone,
        "synthetic": c.filename.startswith("synthetic_"),
    } for c in scoped_clips]

    vehicles = []
    for vehicle in sorted(scoped_vehicles, key=lambda v: (v.clip.camera_label, v.first_seen_sec, v.track_id)):
        result = vehicle.match_result or {}
        vehicles.append({
            "id": vehicle.id, "camera_label": vehicle.clip.camera_label, "track_id": vehicle.track_id,
            "first_seen_sec": vehicle.first_seen_sec, "last_seen_sec": vehicle.last_seen_sec,
            "frames_tracked": vehicle.frames_tracked, "attributes": vehicle.attributes,
            "fused_plate": vehicle.fused_plate, "keyframes": vehicle.keyframes[:1], "match": result,
            "overrides": vehicle.overrides, "outcome": result.get("outcome", "UNREADABLE_PLATE"),
            "outcome_label": OUTCOME_LABELS.get(result.get("outcome", ""), "Not analysed"),
            "attr_line": _attribute_line(vehicle.attributes or {}),
            "provenance": _provenance(vehicle.keyframes[0]) if vehicle.keyframes else "No keyframe stored.",
            "readability": readability(result.get("known_chars", 0)),
            "quality": (vehicle.attributes or {}).get("track_quality") or {},
            "image_warnings": (vehicle.keyframes[0].get("image_warnings") or []) if vehicle.keyframes else [],
            "rejected_reads": (vehicle.fused_plate or {}).get("rejected_reads") or [],
        })
    ranked = sorted((v for v in vehicles if v["outcome"] in OUTCOME_ORDER),
                    key=lambda v: (OUTCOME_ORDER[v["outcome"]],
                                   -((v["match"].get("candidates") or v["match"].get("rejected_candidates")
                                      or [{"score": 0}])[0]["score"])))
    key_vehicles = ranked[:MAX_KEY_VEHICLES]
    evidence_only = sorted(
        (v for v in vehicles if v["outcome"] in {"NO_REGISTRY_COVERAGE", "NO_REGISTRY_MATCH", "INSUFFICIENT_PLATE"}
         and v["keyframes"] and v["keyframes"][0].get("plate_raw")),
        key=lambda v: (-(v["match"].get("known_chars", 0)), -(v["keyframes"][0].get("plate_quality") or 0)),
    )
    ocr_examples = evidence_only[:MAX_OCR_EXAMPLES]
    for vehicle in [*key_vehicles, *ocr_examples]:
        vehicle["keyframes"] = [
            {**frame, "crop_uri": _data_uri(frame.get("crop"), MAX_CROP_WIDTH),
             "frame_uri": _data_uri(frame.get("frame"), MAX_CROP_WIDTH),
             "raw_uri": _data_uri(frame.get("plate_raw")), "enhanced_uri": _data_uri(frame.get("plate_enhanced"))}
            for frame in vehicle["keyframes"]
        ]

    entities = [{
        "id": e.id, "fused_plate": e.fused_plate, "timeline": e.timeline, "links": e.links,
        "match_result": e.match_result, "review_status": e.review_status,
        "status_label": ENTITY_STATUS_LABELS.get(e.review_status, e.review_status),
        "tier_label": EVIDENCE_TIER_LABELS.get(e.evidence_tier, e.evidence_tier),
    } for e in sorted(case.completed_entities, key=lambda item: {"confirmed": 0, "proposed": 1}.get(item.review_status, 2))
        if e.review_status != "rejected" and (clip_id is None or any(t["clip_id"] == clip_id for t in e.timeline))]
    audit = [{"created_at": _iso(e.created_at), "actor": e.actor, "action": e.action, "vehicle_id": e.vehicle_id,
              "field": e.field, "ai_extracted": e.ai_extracted, "investigator_verified": e.investigator_verified,
              "note": e.note} for e in case.audit_events]
    for vehicle in vehicles:
        vehicle["unknown_notes"] = [
            f"Slot {slot['position'] + 1}: {slot['unknown_reason']}"
            + (f" (alternatives: {', '.join(c['char'] + ' ' + format(c['probability'], '.2f') for c in slot['candidates'])})"
               if slot.get("candidates") else "")
            for slot in vehicle["fused_plate"].get("slots", []) if slot.get("char") == "?" and slot.get("unknown_reason")
        ]
    no_match_vehicles = [v for v in vehicles if v["outcome"] == "NO_REGISTRY_MATCH"]
    no_coverage_vehicles = [v for v in vehicles if v["outcome"] == "NO_REGISTRY_COVERAGE"]
    scoped_entities = [e for e in case.completed_entities
                       if clip_id is None or any(t["clip_id"] == clip_id for t in e.timeline)]
    summary = summarise(scoped_vehicles, scoped_entities, scoped_clips, load_registry(session), case.runtime)
    registry_note = summary["registry"]["note"]
    return {
        "case": case, "clips": clips, "vehicles": vehicles, "key_vehicles": key_vehicles,
        "hidden_key": max(len(ranked) - MAX_KEY_VEHICLES, 0), "entities": entities, "audit": audit,
        "overrides": [e for e in audit if e["action"] in {"INVESTIGATOR_OVERRIDE", "OVERRIDE_RESET", "LINK_REVIEWED"}],
        "no_match_rows": no_match_vehicles[:MAX_NO_MATCH_ROWS],
        "hidden_no_match": max(len(no_match_vehicles) - MAX_NO_MATCH_ROWS, 0),
        "audit_recent": audit[-MAX_AUDIT_ROWS:],
        "summary": summary, "headline": headline(summary), "registry_note": registry_note,
        "ocr_examples": ocr_examples, "no_coverage_rows": no_coverage_vehicles[:MAX_COVERAGE_ROWS],
        "hidden_no_coverage": max(len(no_coverage_vehicles) - MAX_COVERAGE_ROWS, 0),
        "rejected_read_vehicles": [v for v in vehicles if v["rejected_reads"]],
        "missing_time": sum(c.recorded_at is None for c in scoped_clips),
        "scope_label": scoped_clips[0].camera_label if clip_id and scoped_clips else None,
        "has_synthetic_clip": any(c["synthetic"] for c in clips),
        "matrix_vehicles": [v for v in vehicles if v["fused_plate"].get("matrix")],
        "generated_at": _iso(datetime.now(timezone.utc)), "appendix": appendix,
    }


def render_html(session: Session, case_id: str, appendix: bool = True, clip_id: str | None = None) -> str:
    case = session.get(Case, case_id)
    if case is None:
        raise KeyError(case_id)
    return _environment.get_template("report.html").render(**build_context(session, case, appendix, clip_id))


def render_pdf(session: Session, case_id: str, appendix: bool = False,
               clip_id: str | None = None) -> tuple[bytes, str]:
    """Return ``(pdf_bytes, engine)``. WeasyPrint needs native libraries, so ReportLab backs it up."""
    html = render_html(session, case_id, appendix, clip_id).replace("<details>", '<details open="">')
    try:
        from weasyprint import HTML

        return HTML(string=html).write_pdf(), "weasyprint"
    except Exception as error:  # OSError on missing Pango/Cairo, or a rendering failure.
        logger.warning("WeasyPrint unavailable, using ReportLab: %s", error)
    case = session.get(Case, case_id)
    return _reportlab_pdf(build_context(session, case, appendix, clip_id)), "reportlab"


def _provenance(frame: dict) -> str:
    if not frame.get("plate_raw"):
        return "No plate crop was recovered for this track."
    size = frame.get("plate_crop_size") or ["?", "?"]
    rectification = (frame.get("rectification") or {}).get("reason", "not recorded")
    box = frame.get("plate_box_source")
    location = f", source box {box}" if box else ""
    return (f"Frame {frame['frame_idx']} at {frame['timestamp_sec']} s{location}, sharpness {frame.get('frame_sharpness', 0)}, "
            f"brightness {frame.get('brightness', 0)}, plate box {frame.get('plate_box_confidence', 0):.2f}, "
            f"crop {size[0]}x{size[1]} px, {frame.get('ocr_engine', 'OCR')}. Perspective: {rectification}.")


def _reportlab_pdf(context: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#475569"))
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=7.5, leading=9.5)
    heading = ParagraphStyle("h", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4, keepWithNext=1)
    sub = ParagraphStyle("sub", parent=styles["Heading3"], fontSize=9.5, spaceBefore=4, spaceAfter=3)
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F8FAFC")),
                       ("VALIGN", (0, 0), (-1, -1), "TOP")])
    full_width = 182 * mm

    def p(value, style=body):
        return Paragraph(escape(str(value if value is not None else "")), style)

    def image(uri: str | None, width: float):
        if not uri:
            return p("")
        decoded = Image(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
        decoded.drawHeight = width * decoded.imageHeight / decoded.imageWidth
        decoded.drawWidth = width
        return decoded

    def table(rows, widths=None):
        return Table(rows, colWidths=widths, style=grid, repeatRows=1)

    case, summary = context["case"], context["summary"]
    tone = "#065F46" if summary["plate_candidates"] else "#92400E" if summary["ambiguous"] \
        or summary["no_registry_coverage"] else "#9F1239"
    verdict = f"{summary['plate_candidates']} plate-supported candidate(s)" if summary["plate_candidates"] else \
        f"No single match, {summary['ambiguous']} ambiguous" if summary["ambiguous"] else \
        "No registry coverage: plates were read but not searched" if summary["no_registry_coverage"] else \
        "No confident match"
    verdict_style = ParagraphStyle("verdict", parent=body, fontSize=12, leading=15, textColor=colors.HexColor(tone),
                                   fontName="Helvetica-Bold")
    story = [
        Paragraph("VITRA Vehicle Identification Forensic Report", styles["Title"]),
        *([p("SYNTHETIC TEST FIXTURE: clips, plates, vehicles and owners are fictional.", verdict_style)]
          if context["has_synthetic_clip"] else []),
        *([p(f"Clip report: {context['scope_label']}", body)] if context["scope_label"] else []),
        p(f"Case {case.id} - {case.title} - Generated {context['generated_at']} UTC - "
          f"Pipeline {case.pipeline_version or 'n/a'}", small),
        Paragraph("Executive Summary", heading), Paragraph(escape(verdict), verdict_style),
        p(f"{summary['tracks']} vehicle track(s) across {len(context['clips'])} clip(s). {context['headline']}"),
    ]
    labels = [("Vehicle tracks", "tracks"), ("Candidates", "plate_candidates"), ("Ambiguous", "ambiguous"),
              ("No match", "no_registry_match"), ("No coverage", "no_registry_coverage"),
              ("Partial plate", "insufficient_plate"), ("Unreadable", "unreadable_plate")]
    story.append(table([[p(label, small) for label, _ in labels], [p(summary[key], mono) for _, key in labels]],
                       [full_width / len(labels)] * len(labels)))
    read_labels = [("Readable plates", "readable_plates"), ("Partial plates", "partial_plates"),
                   ("No characters", "no_plate_chars"), ("Reliable tracks", "tracks_reliable"),
                   ("Tracks to review", "tracks_review"), ("Links to review", "possible_links"),
                   ("Confirmed links", "confirmed_links")]
    story += [Spacer(1, 3), table([[p(label, small) for label, _ in read_labels],
                                   [p(summary[key], mono) for _, key in read_labels]],
                                  [full_width / len(read_labels)] * len(read_labels))]
    story += [Spacer(1, 4), p("Results are investigative leads and do not establish identity. Unreadable characters "
                              f"remain ? and are never inferred. {summary['score_note']} {context['registry_note']}",
                              small),
              p(f"Temporal validation: {summary['temporal_note']}", small),
              p(f"Cross-camera status: {summary['cross_camera_note']}", small),
              Paragraph("Registry Coverage", heading)]
    rows = [[p("Camera"), p("Plate format"), p("Compatible records"), p("Registry records"), p("Status")]]
    rows += [[p(row["camera_label"]), p(row["format_label"]), p(row["compatible_records"], mono),
              p(row["total_records"], mono), p("No coverage" if row["status"] == "no_coverage" else "Covered")]
             for row in summary["coverage"]]
    story.append(table(rows, [40 * mm, 45 * mm, 35 * mm, 32 * mm, 30 * mm]))
    if summary["no_registry_coverage"]:
        story.append(p(f"{summary['no_registry_coverage']} readable plate(s) were not searched. The registry has no "
                       "compatible records for their format. They remain OCR evidence and are not no-match results.",
                       body))
    for hint in summary["format_hints"]:
        story.append(p(hint["message"], body))
    story.append(Paragraph("Evidence Integrity", heading))
    rows = [[p("Camera"), p("File"), p("SHA-256"), p("Capture (UTC)"), p("Technical")]]
    for clip in context["clips"]:
        camera = f"{clip['camera_label']} ({clip['plate_format']})"
        rows.append([p(camera), p(clip["filename"]), p(clip["sha256"], mono), p(clip["recorded_at"] or "Not supplied"),
                     p(f"{clip['width']}x{clip['height']} {clip['fps']} fps {clip['duration_sec']} s {clip['codec']}")])
    story.append(table(rows, [25 * mm, 38 * mm, 62 * mm, 25 * mm, 32 * mm]))

    story.append(Paragraph("Shortlist Results", heading))
    story.append(p("Registry plates are ordered by plate evidence. Attributes only break plate ties.", small))
    if not context["key_vehicles"]:
        story.append(p("No track had enough plate evidence to shortlist a registry vehicle."))
    for vehicle in context["key_vehicles"]:
        match = vehicle["match"]
        frame = vehicle["keyframes"][0] if vehicle["keyframes"] else {}
        pictures = [image(frame.get("crop_uri"), 40 * mm)]
        if frame.get("raw_uri"):
            pictures.append(image(frame["raw_uri"], 40 * mm))
            pictures.append(image(frame.get("enhanced_uri"), 40 * mm))
        rows = [[p("#"), p("Plate"), p("Vehicle"), p("Status"), p("Score")]]
        for candidate in (match["candidates"] or match["rejected_candidates"])[:3]:
            item = candidate["vehicle"]
            rows.append([p(candidate["rank"]), p(item["plate"], mono),
                         p(f"{item['colour']} {item['make']} {item['model']} ({pretty(item['body_type'])})"),
                         p(pretty(item["status"]).lower()), p(f"{candidate['score']:.1f}")])
        block = [Paragraph(escape(f"{vehicle['camera_label']} - Track {vehicle['track_id']} - "
                                  f"{match['query_plate'] or 'plate not read'} - {vehicle['outcome_label']}"), sub),
                 Table([pictures], hAlign="LEFT"), p(vehicle["attr_line"], small),
                 p(_provenance(frame), small),
                 table(rows, [8 * mm, 34 * mm, 90 * mm, 32 * mm, 18 * mm])]
        if vehicle["overrides"]:
            block.append(p(f"Includes investigator-verified values. AI read: "
                           f"{vehicle['fused_plate'].get('text') or 'unread'}", small))
        block += [p(item, small) for item in match["diagnostics"]]
        block += [p(item, small) for item in vehicle["unknown_notes"]]
        lead = (match["candidates"] or match["rejected_candidates"] or [None])[0]
        if lead:
            block += [p(item, small) for item in lead["reasons"][:4]]
        story.append(KeepTogether(block))
    if context["hidden_key"]:
        story.append(p(f"{context['hidden_key']} further track(s) with registry candidates are listed in the appendix.",
                       small))

    def evidence_block(vehicle: dict) -> None:
        frame = vehicle["keyframes"][0] if vehicle["keyframes"] else {}
        rows = [[p("Raw source crop", small), p("Enhanced for viewing (CLAHE)", small)],
                [image(frame.get("raw_uri"), 70 * mm), image(frame.get("enhanced_uri"), 70 * mm)]]
        block = [Paragraph(escape(f"{vehicle['camera_label']} - Track {vehicle['track_id']} - "
                                  f"{vehicle['match'].get('query_plate') or 'plate not read'} - "
                                  f"{vehicle['outcome_label']}"), sub),
                 Table(rows, hAlign="LEFT"), p(_provenance(frame), small)]
        block += [p(item, small) for item in vehicle["image_warnings"]]
        block += [p(item, small) for item in vehicle["unknown_notes"]]
        story.append(KeepTogether(block))

    if context["ocr_examples"]:
        story.append(Paragraph("OCR Evidence Examples", heading))
        story.append(p("Enhanced views help review and do not add source detail.", small))
        for vehicle in context["ocr_examples"]:
            evidence_block(vehicle)

    if context["no_coverage_rows"]:
        story.append(Paragraph("Plates Not Searched: No Registry Coverage", heading))
        rows = [[p("Camera"), p("Track"), p("OCR plate read"), p("Compatible records")]]
        rows += [[p(v["camera_label"]), p(v["track_id"], mono), p(v["match"]["query_plate"], mono),
                  p((v["match"].get("registry_coverage") or {}).get("compatible_records", 0), mono)]
                 for v in context["no_coverage_rows"]]
        story.append(table(rows, [45 * mm, 18 * mm, 60 * mm, 45 * mm]))
        if context["hidden_no_coverage"]:
            story.append(p(f"{context['hidden_no_coverage']} more are listed in the appendix.", small))

    if context["no_match_rows"]:
        story.append(Paragraph("No-Match Outcomes (Compatible Registry Searched)", heading))
        rows = [[p("Camera"), p("Track"), p("Recovered plate"), p("Reason")]]
        rows += [[p(v["camera_label"]), p(v["track_id"], mono), p(v["match"]["query_plate"], mono),
                  p(v["match"]["diagnostics"][0] if v["match"]["diagnostics"] else "No registry match", small)]
                 for v in context["no_match_rows"]]
        story.append(table(rows, [28 * mm, 14 * mm, 34 * mm, 106 * mm]))
        if context["hidden_no_match"]:
            story.append(p(f"{context['hidden_no_match']} more are listed in the appendix.", small))

    story.append(Paragraph("Cross-Camera Links", heading))
    story.append(p(summary["cross_camera_note"], small))
    if context["entities"]:
        rows = [[p("Review status"), p("Evidence"), p("Sightings"), p("Plate if merged"), p("Temporal check")]]
        for entity in context["entities"]:
            sightings = "; ".join(f"{t['camera_label']} {t['plate'] or 'unread'}" for t in entity["timeline"])
            rows.append([p(entity["status_label"]), p(entity["tier_label"]), p(sightings, mono),
                         p(entity["fused_plate"].get("text") or "unread", mono),
                         p("; ".join(link["temporal_note"] for link in entity["links"]), small)])
        story.append(table(rows, [24 * mm, 34 * mm, 48 * mm, 26 * mm, 50 * mm]))
    elif summary["cross_camera_status"] == "evaluated":
        story.append(p("No pair of tracks had enough independent evidence to propose a link."))

    story.append(Paragraph("Audit Log", heading))
    rows = [[p("Time"), p("Actor"), p("Action"), p("Field"), p("AI"), p("Investigator")]]
    rows += [[p(e["created_at"], mono), p(e["actor"]), p(pretty(e["action"]).lower()),
              p((e["field"] or "")[:24]), p((e["ai_extracted"] or "")[:16], mono),
              p(e["investigator_verified"], mono)] for e in context["audit_recent"]]
    story.append(table(rows, [32 * mm, 22 * mm, 44 * mm, 30 * mm, 30 * mm, 24 * mm]))
    story.append(p(f"Showing the latest {len(context['audit_recent'])} of {len(context['audit'])} events.", small))

    if context["appendix"]:
        story += [PageBreak(), Paragraph("Appendix: All Tracks", heading)]
        rows = [[p("Camera"), p("Track"), p("Seen"), p("Fused plate"), p("Outcome"), p("Colour"), p("Body")]]
        for vehicle in context["vehicles"]:
            colours = vehicle["attributes"].get("colours") or []
            rows.append([p(vehicle["camera_label"]), p(vehicle["track_id"], mono),
                         p(f"{vehicle['first_seen_sec']}-{vehicle['last_seen_sec']} s", mono),
                         p(vehicle["match"].get("query_plate") or "not read", mono), p(vehicle["outcome_label"]),
                         p(colours[0]["label"] if colours else "unknown"),
                         p(pretty(vehicle["attributes"]["body_type"]["label"]))])
        story.append(table(rows, [24 * mm, 12 * mm, 28 * mm, 30 * mm, 42 * mm, 18 * mm, 28 * mm]))
        story.append(Paragraph("Appendix: Per-Frame Character Recovery", heading))
        for vehicle in context["matrix_vehicles"]:
            slots = vehicle["fused_plate"]["slots"]
            rows = [[p("Time")] + [p(i + 1) for i in range(len(slots))]]
            rows += [[p("stack" if r.get("derived") else r["timestamp_sec"], mono)]
                     + [p(c["char"], mono) for c in r["cells"]] for r in vehicle["fused_plate"]["matrix"]]
            rows += [[p("Fused")] + [p(s["char"], mono) for s in slots]]
            story.append(KeepTogether([p(f"{vehicle['camera_label']} - Track {vehicle['track_id']}", sub),
                                       table(rows, [18 * mm] + [10 * mm] * len(slots))]))
        if context["rejected_read_vehicles"]:
            story.append(Paragraph("Appendix: Rejected Reads", heading))
            rows = [[p("Camera"), p("Track"), p("Frame"), p("Read"), p("Reason")]]
            rows += [[p(v["camera_label"]), p(v["track_id"], mono), p(r["frame_idx"], mono), p(r["raw_text"], mono),
                      p(r["reason"], small)] for v in context["rejected_read_vehicles"] for r in v["rejected_reads"]]
            story.append(table(rows, [30 * mm, 14 * mm, 16 * mm, 34 * mm, 88 * mm]))
        story.append(Paragraph("Appendix: Audit Log", heading))
        rows = [[p("Time"), p("Actor"), p("Action"), p("Field"), p("Note")]]
        rows += [[p(e["created_at"], mono), p(e["actor"]), p(pretty(e["action"]).lower()), p(e["field"]), p(e["note"])]
                 for e in context["audit"]]
        story.append(table(rows, [32 * mm, 24 * mm, 42 * mm, 34 * mm, 50 * mm]))

    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                      bottomMargin=14 * mm, title=f"Forensic Report {case.id}").build(story)
    return buffer.getvalue()
