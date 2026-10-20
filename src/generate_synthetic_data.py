#!/usr/bin/env python3
"""
generate_synthetic_data.py
==========================
Membuat dataset spasial SINTETIS (data palsu) untuk studi kasus
Smart City Asset Management. Hanya memakai library bawaan Python,
sehingga bisa dijalankan tanpa menginstal GeoPandas.

File yang dihasilkan di folder data/:
  - city_assets.geojson        150 titik aset kota (sengaja ada beberapa data "kotor")
  - city_assets.csv            versi tabular dari aset (kolom latitude/longitude)
  - maintenance_zones.geojson  4 poligon zona pemeliharaan
  - critical_facilities.geojson 8 titik fasilitas kritis (rumah sakit, sekolah, dll.)

Data kotor yang disuntikkan (untuk didemonstrasikan di tahap Cleaning):
  - 2 record duplikat (asset_id sama)
  - 1 record dengan koordinat (0, 0) di luar area kota
  - 3 record dengan kondisi kosong (null)
  - 3 record dengan penulisan tipe aset tidak konsisten (huruf besar/kecil, spasi)

Cara pakai:
    python src/generate_synthetic_data.py
"""

import copy
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

# --------------------------------------------------------------------------
# KONFIGURASI
# --------------------------------------------------------------------------
SEED = 42                      # seed tetap -> hasil selalu sama (reproducible)
REFERENCE_YEAR = 2026          # tahun acuan untuk menghitung umur aset
N_BASE_ASSETS = 147            # 147 + 2 duplikat + 1 out-of-bounds = 150 record

# Area studi fiktif: sekitar pusat kota Auckland, Selandia Baru
# (dipilih agar selaras dengan konteks narasumber di New Zealand).
LON_MIN, LON_MAX = 174.745, 174.785
LAT_MIN, LAT_MAX = -36.865, -36.835

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# Spesifikasi tiap tipe aset:
#   lifespan = umur desain (tahun), weight = proporsi kemunculan,
#   cost     = estimasi biaya penggantian (NZD, angka fiktif)
ASSET_SPECS = {
    "Streetlight":         {"lifespan": 20, "weight": 40, "cost": 4500},
    "Fire Hydrant":        {"lifespan": 40, "weight": 12, "cost": 3500},
    "Park Bench":          {"lifespan": 15, "weight": 15, "cost": 1200},
    "Waste Bin":           {"lifespan": 10, "weight": 12, "cost": 800},
    "Bus Stop Shelter":    {"lifespan": 25, "weight": 8,  "cost": 9000},
    "Playground Equipment": {"lifespan": 20, "weight": 5,  "cost": 25000},
    "Drinking Fountain":   {"lifespan": 15, "weight": 4,  "cost": 3000},
    "CCTV Camera":         {"lifespan": 10, "weight": 4,  "cost": 5500},
}

# Zona pemeliharaan: 4 poligon yang saling berbagi sisi (tiling penuh area studi).
TL = (174.745, -36.835)   # top-left
TR = (174.785, -36.835)   # top-right
BL = (174.745, -36.865)   # bottom-left
BR = (174.785, -36.865)   # bottom-right
T = (174.763, -36.835)    # titik tengah sisi atas
Bm = (174.768, -36.865)   # titik tengah sisi bawah
L = (174.745, -36.851)    # titik tengah sisi kiri
R = (174.785, -36.848)    # titik tengah sisi kanan
M = (174.766, -36.8495)   # titik pusat

ZONES = [
    {"zone_id": "Z1", "zone_name": "Zone A - North West", "crew": "Crew Alpha",
     "ring": [TL, L, M, T, TL]},
    {"zone_id": "Z2", "zone_name": "Zone B - North East", "crew": "Crew Bravo",
     "ring": [T, M, R, TR, T]},
    {"zone_id": "Z3", "zone_name": "Zone C - South East", "crew": "Crew Charlie",
     "ring": [M, Bm, BR, R, M]},
    {"zone_id": "Z4", "zone_name": "Zone D - South West", "crew": "Crew Delta",
     "ring": [L, BL, Bm, M, L]},
]

# Fasilitas kritis (nama fiktif) -> dipakai untuk analisis buffer.
FACILITIES = [
    ("F01", "Central General Hospital", "Hospital", 174.7720, -36.8520),
    ("F02", "Harbour View School", "School", 174.7580, -36.8420),
    ("F03", "Eastside Primary School", "School", 174.7790, -36.8430),
    ("F04", "Westgate College", "School", 174.7510, -36.8560),
    ("F05", "Southern Aged Care Home", "Aged Care", 174.7700, -36.8610),
    ("F06", "City Library", "Library", 174.7630, -36.8500),
    ("F07", "Central Fire Station", "Fire Station", 174.7660, -36.8470),
    ("F08", "Community Recreation Centre", "Community Centre", 174.7550, -36.8620),
]


# --------------------------------------------------------------------------
# FUNGSI BANTU
# --------------------------------------------------------------------------
def condition_from_ratio(ratio):
    """Ubah rasio umur/umur-desain menjadi label kondisi dan grade 1-4."""
    if ratio < 0.45:
        return "Good", 1
    if ratio < 0.80:
        return "Fair", 2
    if ratio < 1.05:
        return "Poor", 3
    return "Critical", 4


def make_asset(index):
    """Buat satu record aset acak yang realistis (umur berkorelasi dengan kondisi)."""
    types = list(ASSET_SPECS)
    weights = [ASSET_SPECS[t]["weight"] for t in types]
    asset_type = random.choices(types, weights=weights)[0]
    spec = ASSET_SPECS[asset_type]

    # Rasio umur: 0.05 (hampir baru) sampai 1.2 (melewati umur desain).
    ratio = random.uniform(0.05, 1.2)
    age_years = max(1, round(ratio * spec["lifespan"]))
    install_year = REFERENCE_YEAR - age_years

    # Kondisi = fungsi dari rasio umur + noise, supaya tidak terlalu deterministik.
    condition, grade = condition_from_ratio(ratio + random.gauss(0, 0.15))

    start, end = date(2024, 1, 1), date(2026, 9, 30)
    last_inspection = start + timedelta(days=random.randint(0, (end - start).days))

    lon = round(random.uniform(LON_MIN, LON_MAX), 6)
    lat = round(random.uniform(LAT_MIN, LAT_MAX), 6)

    return {
        "asset_id": f"AST-{index:04d}",
        "asset_type": asset_type,
        "condition": condition,
        "condition_grade": grade,
        "install_year": install_year,
        "last_inspection": last_inspection.isoformat(),
        "replacement_cost_nzd": spec["cost"],
        "latitude": lat,
        "longitude": lon,
    }


def to_feature(record):
    """Ubah record dict menjadi GeoJSON Feature bertipe Point."""
    return {
        "type": "Feature",
        "properties": {k: v for k, v in record.items()},
        "geometry": {"type": "Point", "coordinates": [record["longitude"], record["latitude"]]},
    }


def write_feature_collection(path, name, features):
    """Tulis GeoJSON satu-fitur-per-baris agar mudah dibaca & diff di Git."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'{{"type": "FeatureCollection", "name": "{name}", "features": [\n')
        f.write(",\n".join(json.dumps(ft, ensure_ascii=False) for ft in features))
        f.write("\n]}\n")


# --------------------------------------------------------------------------
# PROGRAM UTAMA
# --------------------------------------------------------------------------
def main():
    random.seed(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Aset dasar yang "bersih"
    records = [make_asset(i) for i in range(1, N_BASE_ASSETS + 1)]

    # 2) Suntik data kotor agar tahap cleaning punya pekerjaan nyata
    dirty_idx = random.sample(range(N_BASE_ASSETS), 6)
    for i in dirty_idx[:3]:                      # kondisi kosong
        records[i]["condition"] = None
        records[i]["condition_grade"] = None
    messy_names = ["  streetlight ", "PARK BENCH", "waste bin"]
    for i, messy in zip(dirty_idx[3:], messy_names):   # tipe aset tidak konsisten
        records[i]["asset_type"] = messy

    # 3) Dua duplikat persis (asset_id sama)
    records.append(copy.deepcopy(records[10]))
    records.append(copy.deepcopy(records[55]))

    # 4) Satu titik salah koordinat (0, 0) = "Null Island", jauh di luar kota
    bad = make_asset(N_BASE_ASSETS + 1)
    bad["latitude"], bad["longitude"] = 0.0, 0.0
    records.append(bad)

    # --- Tulis city_assets.geojson dan city_assets.csv ---------------------
    write_feature_collection(DATA_DIR / "city_assets.geojson", "city_assets",
                             [to_feature(r) for r in records])

    fieldnames = list(records[0].keys())
    with open(DATA_DIR / "city_assets.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    # --- Tulis maintenance_zones.geojson ----------------------------------
    zone_features = [{
        "type": "Feature",
        "properties": {"zone_id": z["zone_id"], "zone_name": z["zone_name"], "crew": z["crew"]},
        "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in z["ring"]]]},
    } for z in ZONES]
    write_feature_collection(DATA_DIR / "maintenance_zones.geojson", "maintenance_zones", zone_features)

    # --- Tulis critical_facilities.geojson --------------------------------
    facility_features = [{
        "type": "Feature",
        "properties": {"facility_id": fid, "facility_name": name, "facility_type": ftype},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    } for fid, name, ftype, lon, lat in FACILITIES]
    write_feature_collection(DATA_DIR / "critical_facilities.geojson", "critical_facilities", facility_features)

    print(f"Selesai. {len(records)} record aset, {len(ZONES)} zona, {len(FACILITIES)} fasilitas kritis")
    print(f"Lokasi: {DATA_DIR}")


if __name__ == "__main__":
    main()
