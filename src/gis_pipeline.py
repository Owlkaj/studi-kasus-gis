#!/usr/bin/env python3
"""
gis_pipeline.py
===============
Pipeline otomatisasi data aset kota (Smart City Asset Management)
berbasis Python + GeoPandas + Shapely + Folium + Matplotlib.

Alur (satu perintah, tanpa intervensi manual):

    [1] LOAD      Baca aset, zona, fasilitas kritis (GeoJSON / CSV)
    [2] CLEAN     Buang duplikat, geometri kosong, titik di luar kota, rapikan teks
    [3] ANALYZE   Spatial join (zona), buffer fasilitas kritis, jarak terdekat,
                  hitung skor prioritas perawatan
    [4] EXPORT    GeoJSON (untuk Web Map), CSV, skrip SQL PostGIS (+ opsional langsung ke DB)
    [5] VISUALIZE Peta statis (PNG), grafik ringkasan (PNG), peta web interaktif (HTML)

Cara pakai:
    python src/gis_pipeline.py
    python src/gis_pipeline.py --buffer-m 500 --reference-date 2026-10-20
    python src/gis_pipeline.py --postgis-url postgresql://user:pass@localhost:5432/gisdb
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")  # backend tanpa layar -> aman dijalankan di server / GitHub Actions
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch
from shapely.geometry import box

# ==========================================================================
# KONFIGURASI
# ==========================================================================
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

CRS_WGS84 = "EPSG:4326"    # lat/lon (standar GeoJSON & web map)
CRS_METRIC = "EPSG:2193"   # NZTM2000 (meter) -> wajib untuk buffer & jarak yang akurat

# Batas wajar area kota (minx, miny, maxx, maxy) dalam lon/lat.
# Titik di luar kotak ini dianggap salah input dan dibuang.
CITY_BBOX = (174.70, -36.90, 174.82, -36.80)

DEFAULT_BUFFER_M = 300              # radius zona layanan fasilitas kritis (meter)
INSPECTION_INTERVAL_DAYS = 365      # inspeksi dianggap terlambat bila > 1 tahun

# Umur desain tiap tipe aset (tahun).
ASSET_LIFESPAN = {
    "Streetlight": 20,
    "Fire Hydrant": 40,
    "Park Bench": 15,
    "Waste Bin": 10,
    "Bus Stop Shelter": 25,
    "Playground Equipment": 20,
    "Drinking Fountain": 15,
    "CCTV Camera": 10,
}

# Poin risiko berdasarkan kondisi fisik. "Unknown" diberi poin sedang
# karena kondisi yang tidak diketahui = risiko yang belum terukur.
CONDITION_POINTS = {"Good": 0, "Fair": 1, "Poor": 3, "Critical": 5, "Unknown": 2}
VALID_CONDITIONS = ["Good", "Fair", "Poor", "Critical"]

PRIORITY_ORDER = ["Urgent", "High", "Medium", "Low"]
PRIORITY_COLORS = {"Urgent": "#d73027", "High": "#fc8d59", "Medium": "#fee08b", "Low": "#1a9850"}

log = logging.getLogger("gis_pipeline")


# ==========================================================================
# [1] LOADING SPATIAL DATA
# ==========================================================================
def load_spatial_data(path: Path) -> gpd.GeoDataFrame:
    """Baca data spasial dari GeoJSON (atau CSV berkolom latitude/longitude)
    dan pastikan hasilnya berada di CRS WGS84 (EPSG:4326)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File tidak ditemukan: {path}")

    if path.suffix.lower() == ".csv":
        # CSV tidak punya geometri -> bentuk titik dari kolom longitude (x) & latitude (y).
        df = pd.read_csv(path)
        missing = {"latitude", "longitude"} - set(df.columns)
        if missing:
            raise ValueError(f"CSV harus memiliki kolom {sorted(missing)}")
        gdf = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy(df["longitude"], df["latitude"]), crs=CRS_WGS84
        )
    else:
        gdf = gpd.read_file(path)
        if gdf.crs is None:                       # GeoJSON tanpa CRS -> asumsikan WGS84
            gdf = gdf.set_crs(CRS_WGS84)
        elif gdf.crs.to_epsg() != 4326:           # samakan semua layer ke WGS84
            gdf = gdf.to_crs(CRS_WGS84)

    log.info("Loaded %-28s %4d fitur  CRS=%s", path.name, len(gdf), gdf.crs)
    return gdf


# ==========================================================================
# [2] DATA CLEANING
# ==========================================================================
def clean_assets(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    """Bersihkan data aset mentah. Mengembalikan (data bersih, laporan jumlah yang dibuang)."""
    report = {"raw_records": len(gdf)}
    gdf = gdf.copy()

    # (a) Buang geometri kosong / null.
    before = len(gdf)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    report["dropped_empty_geometry"] = before - len(gdf)

    # (b) Spatial filter: buang titik di luar batas kota (mis. koordinat 0,0).
    before = len(gdf)
    gdf = gdf[gdf.geometry.within(box(*CITY_BBOX))]
    report["dropped_outside_city"] = before - len(gdf)

    # (c) Buang duplikat berdasarkan asset_id (simpan kemunculan pertama).
    before = len(gdf)
    gdf = gdf.drop_duplicates(subset="asset_id", keep="first")
    report["dropped_duplicates"] = before - len(gdf)

    # (d) Standarkan nama tipe aset: " streetlight " / "PARK BENCH" -> nama baku.
    canonical = {name.lower(): name for name in ASSET_LIFESPAN}
    gdf["asset_type"] = gdf["asset_type"].astype(str).str.strip().str.lower().map(canonical)
    before = len(gdf)
    gdf = gdf[gdf["asset_type"].notna()]          # tipe tak dikenal dibuang
    report["dropped_unknown_type"] = before - len(gdf)

    # (e) Standarkan kondisi; nilai kosong / tidak valid -> "Unknown".
    cond = gdf["condition"].astype("string").str.strip().str.title()
    gdf["condition"] = cond.where(cond.isin(VALID_CONDITIONS), "Unknown").astype(str)
    report["condition_unknown"] = int((gdf["condition"] == "Unknown").sum())

    # (f) Pastikan tipe data kolom benar (tanggal & angka).
    gdf["last_inspection"] = pd.to_datetime(gdf["last_inspection"], errors="coerce")
    gdf["install_year"] = pd.to_numeric(gdf["install_year"], errors="coerce")
    gdf["replacement_cost_nzd"] = pd.to_numeric(gdf["replacement_cost_nzd"], errors="coerce")

    report["clean_records"] = len(gdf)
    log.info("Cleaning: %s", report)
    return gdf.reset_index(drop=True), report


# ==========================================================================
# [3] SPATIAL ANALYSIS (join, buffer, nearest, scoring)
# ==========================================================================
def _union_all(geoms: gpd.GeoSeries):
    """Gabungkan banyak geometri jadi satu (kompatibel dengan versi GeoPandas baru & lama)."""
    return geoms.union_all() if hasattr(geoms, "union_all") else geoms.unary_union


def enrich_assets(
    assets: gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
    facilities: gpd.GeoDataFrame,
    reference_date: pd.Timestamp,
    buffer_m: float,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Tambahkan atribut hasil analisis spasial ke tiap aset.
    SEMUA input harus sudah dalam CRS metrik (meter)."""
    assets = assets.copy()

    # --- 3a. SPATIAL JOIN: aset berada di zona pemeliharaan mana? ----------
    assets = gpd.sjoin(
        assets, zones[["zone_id", "zone_name", "geometry"]], how="left", predicate="within"
    )
    assets = assets.drop(columns="index_right").drop_duplicates(subset="asset_id")
    assets["zone_id"] = assets["zone_id"].fillna("NA")
    assets["zone_name"] = assets["zone_name"].fillna("Outside Zones")
    assets = assets.reset_index(drop=True)

    # --- 3b. BUFFER ANALYSIS: aset dalam radius N meter dari fasilitas kritis -
    buffers = facilities.copy()
    buffers["geometry"] = facilities.geometry.buffer(buffer_m)   # lingkaran radius N meter
    buffer_union = _union_all(buffers.geometry)                   # satukan semua lingkaran
    assets["in_critical_buffer"] = assets.geometry.within(buffer_union)

    # --- 3c. NEAREST: fasilitas kritis terdekat & jaraknya (meter) ---------
    assets = gpd.sjoin_nearest(
        assets,
        facilities[["facility_name", "geometry"]],
        how="left",
        distance_col="dist_to_facility_m",
    )
    assets = assets.drop(columns="index_right").drop_duplicates(subset="asset_id")
    assets = assets.rename(columns={"facility_name": "nearest_facility"}).reset_index(drop=True)

    # --- 3d. ATRIBUT TURUNAN: umur, rasio umur, keterlambatan inspeksi -----
    lifespan = assets["asset_type"].map(ASSET_LIFESPAN)
    assets["age_years"] = reference_date.year - assets["install_year"]
    assets["age_ratio"] = assets["age_years"] / lifespan          # >= 1.0 -> lewat umur desain
    days_since = (reference_date - assets["last_inspection"]).dt.days
    assets["inspection_overdue"] = days_since.isna() | (days_since > INSPECTION_INTERVAL_DAYS)

    # --- 3e. FILTER KEBUTUHAN PERAWATAN ------------------------------------
    # Perlu perawatan : kondisi Poor/Critical ATAU sudah melewati umur desain.
    # Perlu inspeksi  : kondisi tidak diketahui ATAU inspeksi terlambat.
    assets["needs_maintenance"] = (
        assets["condition"].isin(["Poor", "Critical"]) | (assets["age_ratio"] >= 1.0)
    )
    assets["needs_inspection"] = (assets["condition"] == "Unknown") | assets["inspection_overdue"]

    # --- 3f. SKOR PRIORITAS (0-10) -----------------------------------------
    score = assets["condition"].map(CONDITION_POINTS).astype(int)
    score += np.where(assets["age_ratio"] >= 1.0, 2, np.where(assets["age_ratio"] >= 0.8, 1, 0))
    score += assets["inspection_overdue"].astype(int)
    score += assets["in_critical_buffer"].astype(int) * 2          # dekat fasilitas kritis -> naik
    assets["priority_score"] = score.astype(int)
    assets["priority_level"] = pd.cut(
        assets["priority_score"], bins=[-1, 2, 4, 6, 99], labels=["Low", "Medium", "High", "Urgent"]
    ).astype(str)

    return assets, buffers


def select_priority_assets(assets: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Filter aset yang perlu perawatan, urutkan dari prioritas tertinggi."""
    return assets[assets["needs_maintenance"]].sort_values(
        ["priority_score", "dist_to_facility_m"], ascending=[False, True]
    )


def summarize(assets: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Buat tabel ringkasan per zona dan per tipe aset."""
    flagged = assets[assets["needs_maintenance"]]

    zone_summary = (
        assets.groupby("zone_name")
        .agg(
            total_assets=("asset_id", "count"),
            needs_maintenance=("needs_maintenance", "sum"),
            needs_inspection=("needs_inspection", "sum"),
            urgent=("priority_level", lambda s: int((s == "Urgent").sum())),
            high=("priority_level", lambda s: int((s == "High").sum())),
            avg_priority_score=("priority_score", "mean"),
        )
        .round(2)
        .reset_index()
    )
    cost_zone = flagged.groupby("zone_name")["replacement_cost_nzd"].sum().rename("indicative_cost_nzd")
    zone_summary = zone_summary.merge(cost_zone, on="zone_name", how="left").fillna({"indicative_cost_nzd": 0})

    type_summary = (
        assets.groupby("asset_type")
        .agg(
            total_assets=("asset_id", "count"),
            needs_maintenance=("needs_maintenance", "sum"),
            avg_age_ratio=("age_ratio", "mean"),
            avg_priority_score=("priority_score", "mean"),
        )
        .round(2)
        .reset_index()
    )
    cost_type = flagged.groupby("asset_type")["replacement_cost_nzd"].sum().rename("indicative_cost_nzd")
    type_summary = type_summary.merge(cost_type, on="asset_type", how="left").fillna({"indicative_cost_nzd": 0})
    return zone_summary, type_summary.sort_values("needs_maintenance", ascending=False)


# ==========================================================================
# [4] EXPORT (GeoJSON, CSV, PostGIS)
# ==========================================================================
def prepare_for_export(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Ubah ke WGS84, rapikan kolom tanggal & desimal agar aman ditulis ke GeoJSON/SQL."""
    out = gdf.to_crs(CRS_WGS84).copy()
    if "last_inspection" in out.columns:
        out["last_inspection"] = out["last_inspection"].dt.strftime("%Y-%m-%d")
    for col, digits in [("age_ratio", 2), ("dist_to_facility_m", 1)]:
        if col in out.columns:
            out[col] = out[col].round(digits)
    return out


# Definisi kolom tabel PostGIS: (nama kolom, tipe SQL, jenis nilai)
SQL_COLUMNS = [
    ("asset_id", "TEXT PRIMARY KEY", "text"),
    ("asset_type", "TEXT", "text"),
    ("condition", "TEXT", "text"),
    ("install_year", "INTEGER", "int"),
    ("last_inspection", "DATE", "text"),
    ("zone_name", "TEXT", "text"),
    ("age_ratio", "NUMERIC(5,2)", "num"),
    ("priority_score", "INTEGER", "int"),
    ("priority_level", "TEXT", "text"),
    ("needs_maintenance", "BOOLEAN", "bool"),
    ("needs_inspection", "BOOLEAN", "bool"),
    ("in_critical_buffer", "BOOLEAN", "bool"),
    ("nearest_facility", "TEXT", "text"),
    ("dist_to_facility_m", "NUMERIC(8,1)", "num"),
    ("replacement_cost_nzd", "NUMERIC(12,2)", "num"),
]


def _sql_literal(value, kind: str) -> str:
    """Ubah nilai Python menjadi literal SQL yang aman (escape tanda petik)."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "NULL"
    if kind == "bool":
        return "TRUE" if bool(value) else "FALSE"
    if kind == "int":
        return str(int(value))
    if kind == "num":
        return f"{float(value):.2f}"
    return "'" + str(value).replace("'", "''") + "'"


def export_postgis_sql(gdf_wgs84: gpd.GeoDataFrame, path: Path, schema: str = "asset_mgmt") -> None:
    """Hasilkan skrip .sql: buat skema, tabel, insert data, indeks spasial GIST, dan view.
    Jalankan dengan:  psql -d gisdb -f output/postgis_load.sql"""
    table = f"{schema}.city_assets"
    col_defs = ",\n    ".join(f"{name} {sqltype}" for name, sqltype, _ in SQL_COLUMNS)
    col_names = ", ".join(name for name, _, _ in SQL_COLUMNS)

    lines = [
        "-- ==========================================================",
        "-- Skrip ini dibuat otomatis oleh src/gis_pipeline.py",
        "-- Jalankan: psql -d <nama_db> -f output/postgis_load.sql",
        "-- ==========================================================",
        "CREATE EXTENSION IF NOT EXISTS postgis;",
        f"CREATE SCHEMA IF NOT EXISTS {schema};",
        f"DROP VIEW IF EXISTS {schema}.v_maintenance_priority;",
        f"DROP TABLE IF EXISTS {table};",
        f"CREATE TABLE {table} (\n    {col_defs},\n    geom geometry(Point, 4326)\n);",
        "BEGIN;",
    ]
    for _, row in gdf_wgs84.iterrows():
        values = ", ".join(_sql_literal(row[name], kind) for name, _, kind in SQL_COLUMNS)
        geom = f"ST_SetSRID(ST_MakePoint({row.geometry.x:.6f}, {row.geometry.y:.6f}), 4326)"
        lines.append(f"INSERT INTO {table} ({col_names}, geom) VALUES ({values}, {geom});")
    lines += [
        "COMMIT;",
        f"CREATE INDEX idx_city_assets_geom ON {table} USING GIST (geom);",
        f"CREATE INDEX idx_city_assets_priority ON {table} (priority_level);",
        "-- View siap pakai untuk Web Map (mis. pg_featureserv / GeoServer / QGIS)",
        f"CREATE VIEW {schema}.v_maintenance_priority AS",
        f"    SELECT * FROM {table} WHERE needs_maintenance ORDER BY priority_score DESC;",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Skrip PostGIS ditulis: %s", Path(path).name)


def load_to_postgis(gdf_wgs84: gpd.GeoDataFrame, url: str, schema: str = "asset_mgmt") -> None:
    """(Opsional) Muat langsung ke PostGIS. Butuh: sqlalchemy, geoalchemy2, psycopg2-binary."""
    from sqlalchemy import create_engine, text  # lazy import: dependensi ini opsional

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    gdf_wgs84.to_postgis("city_assets", engine, schema=schema, if_exists="replace", index=False)
    log.info("Data dimuat ke PostGIS: %s.city_assets", schema)


# ==========================================================================
# [5] VISUALISASI
# ==========================================================================
def plot_static_map(assets, zones, buffers, facilities, path: Path) -> None:
    """Peta statis (PNG) dengan Matplotlib. Semua layer dalam CRS metrik."""
    fig, ax = plt.subplots(figsize=(10, 9))

    # Layer paling bawah: area buffer fasilitas kritis (biru transparan).
    buffers.plot(ax=ax, facecolor="#4575b4", alpha=0.12, edgecolor="#4575b4", linewidth=0.8)

    # Batas zona + label nama zona di titik representatif poligon.
    zones.boundary.plot(ax=ax, color="#555555", linewidth=1.3)
    for _, z in zones.iterrows():
        p = z.geometry.representative_point()
        ax.annotate(z["zone_name"], xy=(p.x, p.y), ha="center", fontsize=9,
                    fontweight="bold", color="#333333")

    # Titik aset, diwarnai menurut level prioritas (Low digambar dulu agar Urgent di atas).
    for level in reversed(PRIORITY_ORDER):
        subset = assets[assets["priority_level"] == level]
        if subset.empty:
            continue
        subset.plot(ax=ax, color=PRIORITY_COLORS[level], markersize=28,
                    edgecolor="black", linewidth=0.3, label=f"{level} ({len(subset)})")

    # Fasilitas kritis sebagai segitiga hitam.
    facilities.plot(ax=ax, marker="^", color="black", markersize=70, label="Critical facility")

    handles, labels = ax.get_legend_handles_labels()
    handles.append(Patch(facecolor="#4575b4", alpha=0.25, edgecolor="#4575b4"))
    labels.append("Facility buffer")
    ax.legend(handles, labels, loc="lower left", title="Priority", frameon=True)
    ax.set_title("Smart City Asset Management - Maintenance Priority Map", fontsize=13)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    log.info("Peta statis disimpan: %s", Path(path).name)


def plot_summary_chart(assets: pd.DataFrame, path: Path) -> None:
    """Grafik batang bertumpuk: jumlah aset per tipe, dipecah per level prioritas."""
    pivot = pd.crosstab(assets["asset_type"], assets["priority_level"])
    pivot = pivot.reindex(columns=PRIORITY_ORDER, fill_value=0)
    pivot = pivot.loc[pivot.sum(axis=1).sort_values().index]
    ax = pivot.plot(kind="barh", stacked=True, figsize=(9, 5),
                    color=[PRIORITY_COLORS[c] for c in pivot.columns], edgecolor="black", linewidth=0.3)
    ax.set_xlabel("Jumlah aset")
    ax.set_ylabel("")
    ax.set_title("Distribusi Prioritas Perawatan per Tipe Aset")
    ax.legend(title="Priority")
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    log.info("Grafik ringkasan disimpan: %s", Path(path).name)


def build_web_map(assets, zones, buffers, facilities, path: Path) -> None:
    """Peta web interaktif (HTML) dengan Folium. Semua layer harus dalam WGS84."""
    center = [assets.geometry.y.mean(), assets.geometry.x.mean()]
    m = folium.Map(location=center, zoom_start=14, tiles="CartoDB positron")

    # Layer poligon zona.
    folium.GeoJson(
        zones[["zone_name", "geometry"]],
        name="Maintenance zones",
        style_function=lambda f: {"color": "#555555", "weight": 2, "fillOpacity": 0.03},
        tooltip=folium.GeoJsonTooltip(fields=["zone_name"], aliases=["Zone:"]),
    ).add_to(m)

    # Layer buffer fasilitas kritis.
    folium.GeoJson(
        buffers[["facility_name", "geometry"]],
        name="Facility buffers",
        style_function=lambda f: {"color": "#4575b4", "weight": 1, "fillOpacity": 0.10},
        tooltip=folium.GeoJsonTooltip(fields=["facility_name"], aliases=["Buffer:"]),
        show=True,
    ).add_to(m)

    # Satu FeatureGroup per level prioritas -> bisa di-on/off lewat LayerControl.
    for level in PRIORITY_ORDER:
        group = folium.FeatureGroup(name=f"Priority: {level}")
        for r in assets[assets["priority_level"] == level].itertuples():
            popup_html = (
                f"<b>{r.asset_id}</b> - {r.asset_type}<br>"
                f"Condition: {r.condition}<br>"
                f"Zone: {r.zone_name}<br>"
                f"Priority: <b>{r.priority_level}</b> (score {r.priority_score})<br>"
                f"Nearest facility: {r.nearest_facility} ({r.dist_to_facility_m:.0f} m)<br>"
                f"Last inspection: {r.last_inspection}"
            )
            folium.CircleMarker(
                location=[r.geometry.y, r.geometry.x],
                radius=8 if level == "Urgent" else 6,
                color="black", weight=0.6,
                fill=True, fill_color=PRIORITY_COLORS[level], fill_opacity=0.9,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{r.asset_id} - {r.asset_type}",
            ).add_to(group)
        group.add_to(m)

    # Marker fasilitas kritis.
    fac_group = folium.FeatureGroup(name="Critical facilities")
    for r in facilities.itertuples():
        folium.Marker(
            location=[r.geometry.y, r.geometry.x],
            tooltip=f"{r.facility_name} ({r.facility_type})",
            icon=folium.Icon(color="darkblue", icon="info-sign"),
        ).add_to(fac_group)
    fac_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Legenda sederhana (HTML).
    items = "".join(
        f'<div><span style="background:{PRIORITY_COLORS[l]};width:12px;height:12px;'
        f'display:inline-block;border:1px solid #000;margin-right:6px;"></span>{l}</div>'
        for l in PRIORITY_ORDER
    )
    legend = (
        '<div style="position:fixed;bottom:30px;left:30px;z-index:9999;background:white;'
        'padding:8px 12px;border:1px solid #888;border-radius:6px;font-size:12px;">'
        f"<b>Maintenance priority</b>{items}</div>"
    )
    m.get_root().html.add_child(folium.Element(legend))

    m.save(str(path))
    log.info("Peta web interaktif disimpan: %s", Path(path).name)


# ==========================================================================
# ORKESTRASI PIPELINE
# ==========================================================================
def run_pipeline(args: argparse.Namespace) -> None:
    out_dir = Path(args.output_dir)
    map_dir = out_dir / "maps"
    map_dir.mkdir(parents=True, exist_ok=True)

    reference_date = (
        pd.Timestamp(args.reference_date) if args.reference_date else pd.Timestamp.today().normalize()
    )
    log.info("Tanggal acuan: %s | Radius buffer: %s m", reference_date.date(), args.buffer_m)

    # ---- [1] LOAD ---------------------------------------------------------
    raw_assets = load_spatial_data(args.assets)
    zones = load_spatial_data(args.zones)
    facilities = load_spatial_data(args.facilities)

    # ---- [2] CLEAN --------------------------------------------------------
    clean, report = clean_assets(raw_assets)

    # ---- [3] ANALYZE (di CRS metrik agar buffer & jarak dalam meter) ------
    assets_m, buffers_m = enrich_assets(
        clean.to_crs(CRS_METRIC),
        zones.to_crs(CRS_METRIC),
        facilities.to_crs(CRS_METRIC),
        reference_date,
        args.buffer_m,
    )
    priority_m = select_priority_assets(assets_m)
    zone_summary, type_summary = summarize(assets_m)

    # ---- [4] EXPORT -------------------------------------------------------
    assets_wgs = prepare_for_export(assets_m)
    priority_wgs = prepare_for_export(priority_m)
    buffers_wgs = buffers_m.to_crs(CRS_WGS84)

    assets_wgs.to_file(out_dir / "assets_processed.geojson", driver="GeoJSON")
    priority_wgs.to_file(out_dir / "maintenance_priority.geojson", driver="GeoJSON")
    buffers_wgs[["facility_id", "facility_name", "facility_type", "geometry"]].to_file(
        out_dir / "critical_buffers.geojson", driver="GeoJSON"
    )

    # CSV versi tabular (tanpa geometri, tambah kolom lat/lon).
    csv_df = pd.DataFrame(priority_wgs.drop(columns="geometry"))
    csv_df["longitude"] = priority_wgs.geometry.x.round(6)
    csv_df["latitude"] = priority_wgs.geometry.y.round(6)
    csv_df.to_csv(out_dir / "maintenance_priority.csv", index=False)
    zone_summary.to_csv(out_dir / "zone_summary.csv", index=False)
    type_summary.to_csv(out_dir / "type_summary.csv", index=False)

    export_postgis_sql(assets_wgs, out_dir / "postgis_load.sql")
    postgis_url = args.postgis_url or os.environ.get("POSTGIS_URL")
    if postgis_url:
        load_to_postgis(assets_wgs, postgis_url)

    # ---- [5] VISUALIZE ----------------------------------------------------
    plot_static_map(assets_m, zones.to_crs(CRS_METRIC), buffers_m,
                    facilities.to_crs(CRS_METRIC), map_dir / "map_static.png")
    plot_summary_chart(assets_m, map_dir / "chart_summary.png")
    build_web_map(assets_wgs, zones, buffers_wgs, facilities, map_dir / "map_interactive.html")

    # ---- Ringkasan di terminal -------------------------------------------
    print("\n" + "=" * 64)
    print("RINGKASAN PIPELINE")
    print("=" * 64)
    print(f"Record mentah        : {report['raw_records']}")
    print(f"Record bersih        : {report['clean_records']}")
    print(f"Perlu perawatan      : {len(priority_m)}")
    print(f"Perlu inspeksi       : {int(assets_m['needs_inspection'].sum())}")
    print(f"Estimasi biaya (NZD) : {priority_m['replacement_cost_nzd'].sum():,.0f}")
    print("\nRingkasan per zona:")
    print(zone_summary.to_string(index=False))
    print("\n10 aset prioritas tertinggi:")
    cols = ["asset_id", "asset_type", "condition", "zone_name", "priority_score", "priority_level"]
    print(priority_m[cols].head(10).to_string(index=False))
    print(f"\nOutput tersimpan di: {out_dir}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pipeline GIS manajemen aset kota")
    p.add_argument("--assets", default=str(DATA_DIR / "city_assets.geojson"), help="GeoJSON/CSV aset")
    p.add_argument("--zones", default=str(DATA_DIR / "maintenance_zones.geojson"), help="GeoJSON zona")
    p.add_argument("--facilities", default=str(DATA_DIR / "critical_facilities.geojson"),
                   help="GeoJSON fasilitas kritis")
    p.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Folder output")
    p.add_argument("--buffer-m", type=float, default=DEFAULT_BUFFER_M, help="Radius buffer (meter)")
    p.add_argument("--reference-date", default=None, help="Tanggal acuan YYYY-MM-DD (default: hari ini)")
    p.add_argument("--postgis-url", default=None,
                   help="URL SQLAlchemy PostGIS (atau set env POSTGIS_URL). Opsional.")
    return p.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
                        datefmt="%H:%M:%S")
    run_pipeline(parse_args())
