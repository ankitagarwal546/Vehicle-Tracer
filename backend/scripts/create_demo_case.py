"""Create the labelled synthetic demo case through the running API and check its outcomes."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api")
    parser.add_argument("--clips", type=Path, default=ROOT / "demo_clips")
    args = parser.parse_args()
    manifest_path = args.clips / "synthetic_manifest.json"
    if not manifest_path.exists():
        print("Run scripts/generate_demo_clip.py first.", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text())
    with httpx.Client(timeout=600) as client:
        case = client.post(f"{args.api}/cases", json={
            "title": "SYNTHETIC DEMO: evidence walkthrough",
            "description": manifest["warning"],
        }).raise_for_status().json()
        for item in manifest["scenarios"]:
            data = {"camera_label": item["camera"], "location": item["location"], "plate_format": item["plate_format"],
                    "recorded_at": item["capture_time_local"] or "", "timezone": item["timezone"] or "",
                    "latitude": "" if item["latitude"] is None else str(item["latitude"]),
                    "longitude": "" if item["longitude"] is None else str(item["longitude"])}
            with (args.clips / item["file"]).open("rb") as handle:
                client.post(f"{args.api}/cases/{case['id']}/clips", data=data,
                            files={"files": (item["file"], handle, "video/mp4")}).raise_for_status()
        client.post(f"{args.api}/cases/{case['id']}/analyze").raise_for_status()
        while True:
            detail = client.get(f"{args.api}/cases/{case['id']}").raise_for_status().json()
            if detail["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(1)
        if detail["status"] == "FAILED":
            print(f"Analysis failed: {detail['error']}", file=sys.stderr)
            return 1
        vehicles = client.get(f"{args.api}/cases/{case['id']}/vehicles").raise_for_status().json()
    expected = {item["camera"]: item["expected"] for item in manifest["scenarios"]}
    failures = 0
    for vehicle in vehicles["vehicles"]:
        wanted = expected.get(vehicle["camera_label"])
        verdict = "ok" if wanted == vehicle["outcome"] else "DIFFERENT"
        failures += verdict != "ok"
        print(f"{vehicle['camera_label']:<14}{vehicle['plate'] or 'unread':<12}{vehicle['outcome']:<20}"
              f"expected {wanted} [{verdict}]")
    print(f"Possible links: {len(vehicles['entities'])}")
    print(f"Case: http://127.0.0.1:5173/#/{case['id']}/case")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
