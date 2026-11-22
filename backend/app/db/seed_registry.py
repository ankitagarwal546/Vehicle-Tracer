"""Deterministic synthetic registry. All owners and plates are fictional test data."""
from __future__ import annotations

import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal, init_db
from app.db.models import RegistryVehicle
from app.engine.taxonomy import VEHICLE_TAXONOMY

REGISTRY_SIZE = 600
SEED = 20261123
RTO = {
    "CG": ("Raipur", ["04", "07", "10", "12"]), "MH": ("Pune", ["01", "02", "12", "14", "31"]),
    "DL": ("New Delhi", ["01", "03", "05", "08", "10"]), "KA": ("Bengaluru", ["01", "03", "05", "51"]),
    "GJ": ("Ahmedabad", ["01", "05", "06", "18"]), "TN": ("Chennai", ["01", "07", "09", "22"]),
    "UP": ("Lucknow", ["14", "16", "32", "65"]), "HR": ("Gurugram", ["10", "26", "51", "55"]),
    "RJ": ("Jaipur", ["14", "19", "27"]), "WB": ("Kolkata", ["02", "06", "20", "24"]),
}
SERIES_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
COLOURS = ["white"] * 7 + ["silver"] * 5 + ["grey"] * 4 + ["black"] * 4 + ["red"] * 2 + ["blue"] * 2 + [
    "maroon", "brown", "beige", "green", "orange", "yellow",
]
FIRST = ["Aarav", "Vivaan", "Aditi", "Ishaan", "Diya", "Kabir", "Meera", "Rohan", "Sneha", "Arjun",
         "Kavya", "Nikhil", "Priya", "Rahul", "Ananya", "Farhan", "Harpreet", "Lakshmi", "Tenzin", "Joseph"]
LAST = ["Sharma", "Patel", "Nair", "Reddy", "Singh", "Iyer", "Khan", "Das", "Joshi", "Mehta",
        "Gupta", "Verma", "Kulkarni", "Banerjee", "Pillai", "Yadav", "Fernandes", "Chauhan", "Rao", "Bose"]

# (plate, make, model, body, colour, status). Near-duplicates prove ranking precision.
CONFUSABLE_CLUSTERS = [
    ("MH12DE1433", "Hyundai", "Creta", "suv", "white", "STOLEN_ALERT"),
    ("MH12DF1438", "Hyundai", "Creta", "suv", "silver", "ACTIVE"),
    ("MH12DE1483", "Honda", "City", "sedan", "white", "ACTIVE"),
    ("MH12OE1433", "Tata", "Nexon", "suv", "grey", "ACTIVE"),
    ("DL08CA4829", "Maruti Suzuki", "Swift", "hatchback", "red", "ACTIVE"),
    ("DL08CB4829", "Maruti Suzuki", "Baleno", "hatchback", "maroon", "EXPIRED"),
    ("DL03CA4829", "Hyundai", "i20", "hatchback", "red", "ACTIVE"),
    ("KA05MN7711", "Toyota", "Innova", "suv", "silver", "ACTIVE"),
    ("KA05NM7711", "Toyota", "Innova", "suv", "grey", "ACTIVE"),
    ("KA05MW7117", "Mahindra", "Scorpio", "suv", "black", "STOLEN_ALERT"),
    ("CG04AB5566", "Tata", "Punch", "suv", "blue", "ACTIVE"),
    ("CG04A85566", "Tata", "Tiago", "hatchback", "blue", "ACTIVE"),
    ("CG04AB5S66", "Honda", "Activa", "two-wheeler", "black", "ACTIVE"),
    ("22BH6517AA", "Kia", "Seltos", "suv", "white", "ACTIVE"),
    ("22BH6S17AB", "Kia", "Sonet", "suv", "white", "ACTIVE"),
    ("23BH6517AA", "Mahindra", "XUV700", "suv", "black", "ACTIVE"),
    ("MH14GT7319", "Ashok Leyland", "Viking Bus", "bus", "blue", "STOLEN_ALERT"),
    ("MH14GT7819", "Ashok Leyland", "Viking Bus", "bus", "white", "ACTIVE"),
    ("MH14CT7319", "Tata", "Starbus", "bus", "blue", "ACTIVE"),
]


def _rto_plate(rng: random.Random) -> str:
    state = rng.choice(list(RTO))
    district = rng.choice(RTO[state][1])
    series = "".join(rng.choices(SERIES_LETTERS, k=rng.choice([1, 2, 2, 2])))
    return f"{state}{district}{series}{rng.randint(1, 9999):04d}"


def _bh_plate(rng: random.Random) -> str:
    return f"{rng.randint(21, 26)}BH{rng.randint(1, 9999):04d}{''.join(rng.choices(SERIES_LETTERS, k=2))}"


def build_registry(size: int = REGISTRY_SIZE, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    seen: set[str] = set()

    def owner() -> str:
        return f"{rng.choice(FIRST)} {rng.choice(LAST)}"

    def city(plate: str) -> str:
        return RTO[plate[:2]][0] if plate[:2] in RTO else rng.choice([v[0] for v in RTO.values()])

    for plate, make, model, body, colour, status in CONFUSABLE_CLUSTERS:
        seen.add(plate)
        rows.append({"plate": plate, "make": make, "model": model, "body_type": body, "colour": colour,
                     "year": rng.randint(2016, 2025), "owner_name": owner(), "owner_city": city(plate),
                     "status": status})
    while len(rows) < size:
        plate = _bh_plate(rng) if rng.random() < 0.08 else _rto_plate(rng)
        if plate in seen:
            continue
        seen.add(plate)
        make, model, body = rng.choice(VEHICLE_TAXONOMY)
        roll = rng.random()
        status = "STOLEN_ALERT" if roll < 0.04 else "EXPIRED" if roll < 0.14 else "ACTIVE"
        rows.append({"plate": plate, "make": make, "model": model, "body_type": body,
                     "colour": rng.choice(COLOURS), "year": rng.randint(2010, 2025),
                     "owner_name": owner(), "owner_city": city(plate), "status": status})
    return rows


def seed_registry(session: Session, force: bool = False) -> int:
    existing = session.scalar(select(func.count()).select_from(RegistryVehicle)) or 0
    if existing and not force:
        return existing
    if force:
        session.query(RegistryVehicle).delete()
    session.bulk_insert_mappings(RegistryVehicle, build_registry())
    session.commit()
    return session.scalar(select(func.count()).select_from(RegistryVehicle)) or 0


if __name__ == "__main__":
    init_db()
    with SessionLocal() as db:
        print(f"Registry contains {seed_registry(db)} vehicles")
