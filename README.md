# 🏙️ Smart City Asset Management — Pipeline Otomatisasi GIS dengan Python

> Studi kasus end-to-end: dari data aset lapangan mentah → pembersihan → analisis spasial → GeoJSON / PostGIS → peta web.
> Dibuat sebagai tugas kuliah berdasarkan **Kuliah Praktisi Informatika Webinar #3 — "Career and Competition in Industrial Era with GIS"**
> (Narasumber: Widi Primadepa, Asset Management GIS Analyst, City Care Property New Zealand).

**Penulis:** [Nama Anda] · [NIM] · [Program Studi / Universitas]

---

## 📌 1. Deskripsi Kasus

Pemerintah kota mengelola ribuan aset fisik: lampu jalan, hidran, bangku taman, tempat sampah, halte, alat bermain, CCTV, dan lainnya. Datanya biasanya tersebar di spreadsheet dan hasil survei lapangan, sering **duplikat, tidak konsisten, bahkan salah koordinat**. Akibatnya tim pemeliharaan sulit menjawab pertanyaan dasar:

- Aset mana yang **paling mendesak** diperbaiki atau diganti?
- Aset rusak mana yang berada **dekat rumah sakit atau sekolah** (dampak publik tinggi)?
- Zona mana yang butuh **kru dan anggaran terbesar**?

Proyek ini membangun **data pipeline otomatis** berbasis Python dan *open source GIS* yang menjawab pertanyaan tersebut sekali jalan, tanpa intervensi manual, lalu menyiapkan keluaran untuk **Web Map App** dan **database PostGIS**.

### Kaitan dengan tema webinar
Webinar membahas karier dan kompetisi di era industri melalui GIS. Proyek ini menerjemahkan tema itu ke dalam keterampilan konkret seorang *GIS / Asset Management Analyst* sekaligus *Developer*:

| Kompetensi | Diwujudkan di proyek ini |
|---|---|
| Pengolahan data spasial | GeoPandas + Shapely (titik, poligon, CRS) |
| Analisis spasial | Spatial join, buffer, nearest neighbour, spatial filter |
| Otomatisasi | Satu skrip CLI + GitHub Actions terjadwal |
| Integrasi sistem | Ekspor GeoJSON & skrip SQL PostGIS untuk web map |
| Komunikasi hasil | Peta statis, peta interaktif, rekomendasi pengelolaan |

> ⚠️ **Catatan:** seluruh data pada repositori ini adalah **data sintetis (fiktif)** untuk tujuan pembelajaran. Lokasi acuannya area pusat kota Auckland, Selandia Baru, agar selaras dengan konteks narasumber. Tidak ada data milik City Care Property atau pihak mana pun.

---

## 🗂️ 2. Struktur Repositori

```
city-asset-gis-pipeline/
├── .github/
│   └── workflows/
│       └── pipeline.yml            # Otomatisasi: jalankan pipeline di GitHub Actions
├── data/                           # INPUT (data mentah)
│   ├── city_assets.geojson         # 150 titik aset kota (sengaja ada data kotor)
│   ├── city_assets.csv             # Versi tabular aset (kolom latitude/longitude)
│   ├── maintenance_zones.geojson   # 4 poligon zona pemeliharaan
│   └── critical_facilities.geojson # 8 titik fasilitas kritis (RS, sekolah, dll.)
├── src/                            # KODE SUMBER
│   ├── generate_synthetic_data.py  # Pembuat dataset sintetis (tanpa dependensi)
│   └── gis_pipeline.py             # Pipeline utama GeoPandas
├── output/                         # OUTPUT (dibuat otomatis saat pipeline berjalan)
│   ├── assets_processed.geojson    # Semua aset + atribut hasil analisis
│   ├── maintenance_priority.geojson# Hanya aset yang perlu perawatan (untuk Web Map)
│   ├── critical_buffers.geojson    # Poligon buffer fasilitas kritis
│   ├── maintenance_priority.csv    # Daftar kerja untuk tim lapangan
│   ├── zone_summary.csv            # Ringkasan per zona
│   ├── type_summary.csv            # Ringkasan per tipe aset
│   ├── postgis_load.sql            # Skrip muat ke PostGIS
│   └── maps/
│       ├── map_static.png          # Peta statis (Matplotlib)
│       ├── chart_summary.png       # Grafik ringkasan prioritas
│       └── map_interactive.html    # Peta interaktif (Folium)
├── requirements.txt
├── LICENSE
└── README.md
```

---

## ⚙️ 3. Instalasi

**Prasyarat:** Python 3.9 atau lebih baru.

```bash
# 1. Clone repositori
git clone https://github.com/<username-anda>/city-asset-gis-pipeline.git
cd city-asset-gis-pipeline

# 2. Buat virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Instal library
pip install -r requirements.txt
```

Library utama: `geopandas`, `shapely`, `pyproj`, `pandas`, `numpy`, `matplotlib`, `folium`.

**Alternatif (disarankan untuk Windows jika `pip` bermasalah dengan GDAL/GEOS):**

```bash
conda create -n gis-assets -c conda-forge python=3.11 geopandas folium matplotlib
conda activate gis-assets
```

**Opsional — muat langsung ke PostGIS:**

```bash
pip install sqlalchemy geoalchemy2 psycopg2-binary
```

---

## ▶️ 4. Cara Menjalankan

```bash
# (Opsional) buat ulang dataset sintetis. Hasilnya selalu sama karena seed tetap.
python src/generate_synthetic_data.py

# Jalankan pipeline lengkap
python src/gis_pipeline.py
```

Opsi tambahan:

```bash
# Ubah radius buffer menjadi 500 m dan kunci tanggal acuan (hasil reproducible)
python src/gis_pipeline.py --buffer-m 500 --reference-date 2026-10-20

# Muat langsung ke database PostGIS
python src/gis_pipeline.py --postgis-url postgresql://user:password@localhost:5432/gisdb

# Atau lewat skrip SQL yang dihasilkan
psql -d gisdb -f output/postgis_load.sql
```

Setelah selesai, buka `output/maps/map_interactive.html` di browser.

> 💡 Hasil perhitungan bergantung pada `--reference-date` (default: hari ini), karena umur aset dan keterlambatan inspeksi dihitung terhadap tanggal tersebut.

---

## 🔄 5. Workflow Data: Dari Lapangan hingga Web Map

```mermaid
flowchart LR
    A["Survei lapangan / CSV / IoT"] --> B["1. LOAD<br/>GeoJSON & CSV"]
    B --> C["2. CLEAN<br/>duplikat, koordinat salah,<br/>standarisasi teks"]
    C --> D["3. ANALYZE<br/>spatial join, buffer,<br/>nearest, skor prioritas"]
    D --> E["4. EXPORT"]
    E --> F["GeoJSON"]
    E --> G["Skrip SQL PostGIS"]
    E --> H["CSV kerja tim lapangan"]
    F --> I["Web Map App<br/>Leaflet / OpenLayers / QGIS"]
    G --> J[("PostGIS")]
    J --> I
    D --> K["5. VISUALIZE<br/>PNG & HTML"]
```

### Penjelasan tiap tahap

**1. Load.** `load_spatial_data()` membaca GeoJSON atau CSV (kolom `latitude`/`longitude` diubah menjadi titik dengan `points_from_xy`). Semua layer diseragamkan ke **EPSG:4326**.

**2. Clean.** `clean_assets()` menerapkan aturan kualitas data. Dataset sengaja disuntik data kotor agar tahap ini terlihat dampaknya:

| Masalah di data | Perlakuan |
|---|---|
| 2 record duplikat (`asset_id` sama) | Dibuang, simpan yang pertama |
| 1 titik di koordinat (0, 0) | Dibuang oleh spatial filter (di luar batas kota) |
| 3 kondisi kosong | Diisi `Unknown` dan ditandai butuh inspeksi |
| 3 tipe aset ditulis tidak konsisten (`"  streetlight "`, `"PARK BENCH"`) | Distandarkan ke nama baku |

**3. Analyze.** Seluruh layer diproyeksikan ke **EPSG:2193 (NZTM2000, satuan meter)** supaya buffer dan jarak benar-benar dalam meter. Menghitung buffer atau jarak langsung di derajat (EPSG:4326) akan menghasilkan angka yang keliru.

- **Spatial join** (`sjoin`, predikat `within`): menentukan tiap aset berada di zona pemeliharaan mana.
- **Buffer analysis**: lingkaran radius 300 m (bisa diubah) di sekitar fasilitas kritis; aset di dalamnya mendapat tambahan skor.
- **Nearest neighbour** (`sjoin_nearest`): fasilitas kritis terdekat beserta jaraknya.
- **Spatial filter**: memilih aset yang perlu perawatan dan mengurutkannya.

**4. Export.** Data dikembalikan ke WGS84 lalu ditulis ke GeoJSON, CSV, dan skrip SQL PostGIS (tabel, `INSERT` dengan `ST_MakePoint`, indeks spasial GIST, serta view `v_maintenance_priority`).

**5. Visualize.** Peta statis dan grafik (Matplotlib) serta peta web interaktif dengan layer toggle, popup, dan legenda (Folium).

---

## 🧮 6. Metodologi Skor Prioritas

Setiap aset mendapat skor 0–10 dari penjumlahan:

| Faktor | Poin |
|---|---|
| Kondisi fisik: Good / Fair / Poor / Critical / Unknown | 0 / 1 / 3 / 5 / 2 |
| Rasio umur (umur ÷ umur desain) ≥ 1,0 (lewat umur desain) | +2 |
| Rasio umur 0,8–0,99 (mendekati umur desain) | +1 |
| Inspeksi terakhir lebih dari 365 hari lalu (atau tidak ada) | +1 |
| Berada dalam buffer fasilitas kritis | +2 |

**Level prioritas:** `Low` (0–2) · `Medium` (3–4) · `High` (5–6) · `Urgent` (≥ 7).

Sebuah aset ditandai **perlu perawatan** jika kondisinya `Poor`/`Critical` **atau** sudah melewati umur desain. Ia ditandai **perlu inspeksi** jika kondisinya `Unknown` atau inspeksi terlambat.

> Bobot dan ambang batas adalah asumsi untuk keperluan studi kasus. Pada praktik nyata, nilainya disesuaikan dengan kebijakan dan standar organisasi pengelola aset.

---

## 🗺️ 7. Output & Visualisasi

Jalankan pipeline terlebih dahulu; berkas gambar di bawah baru tersedia setelah itu. Disarankan meng-commit hasilnya agar tampil di GitHub.

**Peta prioritas perawatan (statis)**

![Peta statis](output/maps/map_static.png)

**Distribusi prioritas per tipe aset**

![Grafik ringkasan](output/maps/chart_summary.png)

**Peta interaktif:** buka `output/maps/map_interactive.html` (layer per level prioritas, popup detail aset, buffer fasilitas kritis, dan legenda).

### Contoh konsumsi GeoJSON di Web Map (Leaflet)

```html
<div id="map" style="height:500px"></div>
<script>
  const map = L.map("map").setView([-36.85, 174.765], 14);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);

  fetch("output/maintenance_priority.geojson")
    .then(r => r.json())
    .then(data => L.geoJSON(data, {
      pointToLayer: (f, latlng) => L.circleMarker(latlng, {
        radius: 6,
        color: f.properties.priority_level === "Urgent" ? "#d73027" : "#fc8d59"
      }).bindPopup(`${f.properties.asset_id} - ${f.properties.asset_type}`)
    }).addTo(map));
</script>
```

### Integrasi PostGIS

Setelah `postgis_load.sql` dijalankan, tabel `asset_mgmt.city_assets` dan view `asset_mgmt.v_maintenance_priority` dapat langsung dipakai oleh QGIS, GeoServer, atau layanan *feature server* seperti `pg_featureserv` sebagai sumber data Web Map.

```sql
-- Contoh: aset Urgent dalam radius 300 m dari rumah sakit
SELECT asset_id, asset_type, priority_score
FROM asset_mgmt.city_assets
WHERE priority_level = 'Urgent' AND in_critical_buffer
ORDER BY priority_score DESC;
```

---

## ✅ 8. Rekomendasi Pengelolaan Aset

Rekomendasi berikut dirumuskan dari logika analisis proyek. Jalankan pipeline dan lihat `zone_summary.csv` serta `type_summary.csv` untuk angka aktualnya.

1. **Tangani level *Urgent* lebih dulu**, terutama aset yang berada dalam buffer rumah sakit, sekolah, dan panti jompo, karena kegagalannya berdampak langsung pada keselamatan publik.
2. **Susun rute kerja per zona.** Gunakan `zone_summary.csv` untuk menyeimbangkan beban tiap kru dan memperkirakan anggaran (`indicative_cost_nzd`).
3. **Jadwalkan inspeksi untuk aset berkondisi `Unknown` dan inspeksi terlambat.** Data yang tidak lengkap adalah risiko yang belum terukur.
4. **Perencanaan penggantian berbasis umur.** Aset dengan rasio umur ≥ 0,8 masuk daftar pantau sebelum rusak, sehingga perawatan bersifat preventif, bukan reaktif.
5. **Perbaiki kualitas data di sumber.** Validasi formulir lapangan (daftar pilihan tipe aset, batas koordinat) mencegah duplikat dan salah koordinat sejak awal.
6. **Otomatisasi berkala.** Jadwalkan pipeline (GitHub Actions, cron, atau Airflow) agar peta dan database selalu mutakhir tanpa kerja manual.

---

## 🤖 9. Otomatisasi (Data Pipeline Tanpa Intervensi Manual)

Berkas `.github/workflows/pipeline.yml` menjalankan pipeline secara otomatis ketika:

- ada perubahan pada folder `data/` atau `src/` (`push`),
- sesuai jadwal mingguan (`cron`),
- dipicu manual dari tab **Actions** (`workflow_dispatch`).

Hasilnya diunggah sebagai *artifact* (`gis-pipeline-output`) yang bisa diunduh dari halaman run.

---

## ⚠️ 10. Keterbatasan & Pengembangan Lanjutan

**Keterbatasan**
- Data sintetis; bobot skor adalah asumsi.
- Aset dimodelkan sebagai titik. Aset linier (pipa, jalan) memerlukan *LineString* dan analisis tambahan.
- Hanya satu radius buffer untuk semua jenis fasilitas.

**Ide pengembangan**
- Mengganti data sintetis dengan data terbuka (mis. OpenStreetMap lewat `osmnx`).
- Analisis rute optimal untuk kru lapangan (`networkx` / `osmnx`).
- Menambah *unit test* (`pytest`) dan validasi skema (`pandera`).
- Dashboard interaktif (Streamlit) dan *feature server* langsung dari PostGIS.

---

## 📚 11. Referensi

- GeoPandas Documentation — https://geopandas.org
- Shapely Documentation — https://shapely.readthedocs.io
- Folium Documentation — https://python-visualization.github.io/folium
- PostGIS Documentation — https://postgis.net/documentation
- Kuliah Praktisi Informatika Webinar #3: *Career and Competition in Industrial Era with GIS*

## 📄 Lisensi

Dirilis di bawah lisensi MIT — lihat berkas [LICENSE](LICENSE).
