"""Curated make/model taxonomy shared by the registry seeder and the CLIP classifier."""
from __future__ import annotations

VEHICLE_TAXONOMY: tuple[tuple[str, str, str], ...] = (
    ("Maruti Suzuki", "Swift", "hatchback"), ("Maruti Suzuki", "Baleno", "hatchback"),
    ("Maruti Suzuki", "WagonR", "hatchback"), ("Maruti Suzuki", "Alto", "hatchback"),
    ("Maruti Suzuki", "Dzire", "sedan"), ("Maruti Suzuki", "Ciaz", "sedan"),
    ("Maruti Suzuki", "Ertiga", "suv"), ("Maruti Suzuki", "Brezza", "suv"),
    ("Maruti Suzuki", "Eeco", "van"),
    ("Hyundai", "i10", "hatchback"), ("Hyundai", "i20", "hatchback"),
    ("Hyundai", "Verna", "sedan"), ("Hyundai", "Aura", "sedan"),
    ("Hyundai", "Creta", "suv"), ("Hyundai", "Venue", "suv"),
    ("Tata", "Tiago", "hatchback"), ("Tata", "Altroz", "hatchback"), ("Tata", "Tigor", "sedan"),
    ("Tata", "Nexon", "suv"), ("Tata", "Punch", "suv"), ("Tata", "Harrier", "suv"),
    ("Tata", "Ace", "pickup_truck"), ("Tata", "LPT Truck", "heavy_truck"), ("Tata", "Starbus", "bus"),
    ("Mahindra", "Scorpio", "suv"), ("Mahindra", "XUV700", "suv"), ("Mahindra", "Bolero", "suv"),
    ("Mahindra", "Thar", "suv"), ("Mahindra", "Bolero Pickup", "pickup_truck"),
    ("Toyota", "Innova", "suv"), ("Toyota", "Fortuner", "suv"), ("Toyota", "Glanza", "hatchback"),
    ("Honda", "City", "sedan"), ("Honda", "Amaze", "sedan"),
    ("Kia", "Seltos", "suv"), ("Kia", "Sonet", "suv"),
    ("Force", "Traveller", "van"),
    ("Honda", "Activa", "two-wheeler"), ("TVS", "Jupiter", "two-wheeler"), ("TVS", "Apache", "two-wheeler"),
    ("Hero", "Splendor", "two-wheeler"), ("Bajaj", "Pulsar", "two-wheeler"),
    ("Royal Enfield", "Classic", "two-wheeler"),
    ("Bajaj", "RE Auto-Rickshaw", "auto-rickshaw"), ("Piaggio", "Ape Auto", "auto-rickshaw"),
    ("Ashok Leyland", "Dost", "pickup_truck"), ("Ashok Leyland", "Truck", "heavy_truck"),
    ("Ashok Leyland", "Viking Bus", "bus"), ("Eicher", "Pro Truck", "heavy_truck"),
)
