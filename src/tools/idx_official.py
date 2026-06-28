"""
IDX Official Data Tools — via curl_cffi (browser impersonation).

Mengambil data resmi dari IDX (idx.co.id) yang sebelumnya diblock Cloudflare.
curl_cffi dengan impersonate='chrome' berhasil bypass proteksi tersebut.

Tools:
  - get_financial_report  : Cek LK quarterly per emiten (TW1-TW4, per tahun)
  - get_company_profile   : Profil lengkap emiten (direksi, komisaris, sekretaris)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

try:
    from curl_cffi import requests as cffi_requests
    _CFFI_AVAILABLE = True
except ImportError:
    _CFFI_AVAILABLE = False

from mcp.types import Tool

IDX_BASE = "https://www.idx.co.id/primary/ListedCompany"
IDX_PDF_BASE = "https://www.idx.co.id"
_TIMEOUT = 15

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "Referer": "https://www.idx.co.id/",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

_VALID_TICKER = re.compile(r"^[A-Z]{1,5}$")
_PERIODE_MAP = {
    "Q1": "TW1", "TW1": "TW1",
    "Q2": "TW2", "TW2": "TW2",
    "Q3": "TW3", "TW3": "TW3",
    "Q4": "TW4", "TW4": "TW4",
}

# ── helpers ────────────────────────────────────────────────────────────────────

def _clean_ticker(ticker: str) -> str:
    t = ticker.strip().upper().replace(".JK", "")
    return t

def _get(url: str) -> Optional[dict]:
    if not _CFFI_AVAILABLE:
        return None
    try:
        r = cffi_requests.get(url, headers=_HEADERS, impersonate="chrome", timeout=_TIMEOUT)
        if r.status_code == 200 and r.text.strip():
            return r.json()
        return None
    except Exception:
        return None


# ── 1. Financial Report ────────────────────────────────────────────────────────

def fetch_financial_report(
    ticker: str,
    year: Optional[int] = None,
    quarter: Optional[str] = None,
) -> dict:
    """
    Cek laporan keuangan (LK) emiten dari IDX official.

    Bisa cek satu periode (year+quarter), semua quarter dalam satu tahun,
    atau semua tahun yang tersedia (3 tahun terakhir).
    """
    if not _CFFI_AVAILABLE:
        return {"error": "curl_cffi tidak terinstall. Jalankan: pip install curl_cffi"}

    ticker = _clean_ticker(ticker)
    if not _VALID_TICKER.match(ticker):
        return {"error": f"Ticker tidak valid: {ticker}"}

    current_year = datetime.now().year

    # Tentukan range tahun & periode yang akan dicek
    if year and quarter:
        # Spesifik: satu periode
        periode = _PERIODE_MAP.get(quarter.upper())
        if not periode:
            return {"error": f"Quarter tidak valid: {quarter}. Gunakan Q1/Q2/Q3/Q4 atau TW1/TW2/TW3/TW4"}
        years_to_check = [str(year)]
        periodes_to_check = [periode]
    elif year:
        # Semua quarter tahun tersebut
        years_to_check = [str(year)]
        periodes_to_check = ["TW1", "TW2", "TW3", "TW4"]
    else:
        # 3 tahun terakhir, semua quarter
        years_to_check = [str(current_year), str(current_year - 1), str(current_year - 2)]
        periodes_to_check = ["TW1", "TW2", "TW3", "TW4"]

    results = []
    for yr in years_to_check:
        for per in periodes_to_check:
            url = (
                f"{IDX_BASE}/GetFinancialReport"
                f"?KodeEmiten={ticker}&ReportType=LK&Year={yr}&Periode={per}"
            )
            data = _get(url)
            if not data:
                continue

            count = data.get("ResultCount", 0)
            quarter_label = per.replace("TW", "Q")

            if count == 0:
                results.append({
                    "year": yr,
                    "quarter": quarter_label,
                    "status": "NOT PUBLISHED",
                    "published_date": None,
                    "files": [],
                })
                continue

            row = data["Results"][0]
            published = row.get("File_Modified", "")
            # Format tanggal
            try:
                pub_dt = datetime.fromisoformat(published)
                published_str = pub_dt.strftime("%Y-%m-%d")
            except Exception:
                published_str = published[:10] if published else None

            attachments = row.get("Attachments", [])
            files = []
            for att in attachments:
                fname = att.get("File_Name", "")
                fpath = att.get("File_Path", "")
                ftype = att.get("File_Type", "")
                # Hanya ambil file LK (bukan Annual Report / ESG)
                is_lk = any(k in fname.upper() for k in ["LK", "FINSTAT", "FINANCIAL", "LAPORAN"])
                is_ar = any(k in fname.upper() for k in ["ANNUAL", "ESG", "TAHUNAN"])
                files.append({
                    "filename": fname,
                    "url": IDX_PDF_BASE + fpath if fpath else None,
                    "type": ftype,
                    "category": "Annual Report" if is_ar else ("LK" if is_lk else "Other"),
                })

            # Cari LK file
            lk_files = [f for f in files if f["category"] == "LK"]
            other_files = [f for f in files if f["category"] != "LK"]

            results.append({
                "year": yr,
                "quarter": quarter_label,
                "status": "PUBLISHED",
                "published_date": published_str,
                "emiten": row.get("NamaEmiten", ticker),
                "lk_files": lk_files,
                "other_files": other_files,
            })

    if not results:
        return {
            "ticker": ticker,
            "error": "Tidak ada data. Pastikan kode emiten benar.",
        }

    # Summary
    published = [r for r in results if r["status"] == "PUBLISHED"]
    not_published = [r for r in results if r["status"] == "NOT PUBLISHED"]
    latest = published[-1] if published else None

    return {
        "ticker": ticker,
        "query": {
            "years": years_to_check,
            "quarters": [p.replace("TW", "Q") for p in periodes_to_check],
        },
        "summary": {
            "total_published": len(published),
            "total_not_published": len(not_published),
            "latest_published": f"{latest['year']} {latest['quarter']}" if latest else None,
            "latest_published_date": latest["published_date"] if latest else None,
        },
        "reports": results,
    }


# ── 2. Company Profile ─────────────────────────────────────────────────────────

def fetch_company_profile(ticker: str) -> dict:
    """
    Profil lengkap emiten dari IDX: info perusahaan, direksi, komisaris,
    sekretaris perusahaan, dan daftar efek yang dicatatkan.
    """
    if not _CFFI_AVAILABLE:
        return {"error": "curl_cffi tidak terinstall. Jalankan: pip install curl_cffi"}

    ticker = _clean_ticker(ticker)
    if not _VALID_TICKER.match(ticker):
        return {"error": f"Ticker tidak valid: {ticker}"}

    url = f"{IDX_BASE}/GetCompanyProfilesDetail?KodeEmiten={ticker}&language=id-id"
    data = _get(url)

    if not data or data.get("ResultCount", 0) == 0:
        return {"error": f"Data profil tidak ditemukan untuk {ticker}"}

    profiles = data.get("Profiles", [])
    if not profiles:
        return {"error": f"Profil kosong untuk {ticker}"}

    p = profiles[0]

    # Listing date
    listing_date = p.get("TanggalPencatatan", "")
    try:
        listing_dt = datetime.fromisoformat(listing_date)
        listing_str = listing_dt.strftime("%Y-%m-%d")
    except Exception:
        listing_str = listing_date[:10] if listing_date else None

    # Efek yang dicatatkan
    efek = []
    if p.get("EfekEmiten_Saham"):
        efek.append("Saham")
    if p.get("EfekEmiten_Obligasi"):
        efek.append("Obligasi")
    if p.get("EfekEmiten_ETF"):
        efek.append("ETF")
    if p.get("EfekEmiten_EBA"):
        efek.append("EBA")

    # Logo URL
    logo = p.get("Logo", "")
    logo_url = IDX_PDF_BASE + logo if logo else None

    # Direksi
    direktur = []
    for d in data.get("Direktur", []):
        direktur.append({
            "nama": d.get("Nama", ""),
            "jabatan": d.get("Jabatan", ""),
            "afiliasi": d.get("Afiliasi", False),
        })

    # Komisaris
    komisaris = []
    for k in data.get("Komisaris", []):
        komisaris.append({
            "nama": k.get("Nama", ""),
            "jabatan": k.get("Jabatan", ""),
            "independen": k.get("Independen", False),
        })

    # Sekretaris
    sekretaris = []
    for s in data.get("Sekretaris", []):
        sekretaris.append({
            "nama": s.get("Nama", ""),
            "email": s.get("Email", ""),
            "telepon": s.get("Telepon", ""),
        })

    return {
        "ticker": ticker,
        "nama_emiten": p.get("NamaEmiten", ""),
        "kegiatan_usaha": (p.get("KegiatanUsahaUtama") or "").strip(),
        "sektor": p.get("Sektor", ""),
        "sub_sektor": p.get("SubSektor", ""),
        "industri": p.get("Industri", ""),
        "sub_industri": p.get("SubIndustri", ""),
        "papan_pencatatan": p.get("PapanPencatatan", ""),
        "tanggal_listing": listing_str,
        "efek_tercatat": efek,
        "alamat": (p.get("Alamat") or "").replace("\r\n", ", "),
        "telepon": p.get("Telepon", ""),
        "email": p.get("Email", ""),
        "website": p.get("Website", ""),
        "logo_url": logo_url,
        "direksi": direktur,
        "komisaris": komisaris,
        "sekretaris_perusahaan": sekretaris,
        "source": "IDX Official (idx.co.id)",
    }


# ── MCP Tool Wrappers ──────────────────────────────────────────────────────────

def get_financial_report_tool() -> Tool:
    return Tool(
        name="get_financial_report",
        description=(
            "Cek laporan keuangan (LK) emiten dari IDX official. "
            "Bisa cek apakah LK sudah dipublikasi untuk periode tertentu (Q1/Q2/Q3/Q4), "
            "beserta tanggal publikasi dan link PDF-nya. "
            "Kalau tidak ada year/quarter, tampilkan 3 tahun terakhir semua quarter. "
            "Gunakan untuk jawab: 'LK Q4 2025 BBCA sudah keluar?', "
            "'ZATA sudah lapor Q1 2025 belum?', 'download LK terbaru TLKM'"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Kode emiten IDX (contoh: BBCA, ZATA, TLKM)"
                },
                "year": {
                    "type": "integer",
                    "description": "Tahun laporan (contoh: 2025). Opsional."
                },
                "quarter": {
                    "type": "string",
                    "description": "Quarter: Q1/Q2/Q3/Q4 atau TW1/TW2/TW3/TW4. Opsional."
                }
            },
            "required": ["ticker"]
        }
    )


async def get_financial_report(arguments: dict) -> dict:
    return fetch_financial_report(
        ticker=arguments.get("ticker", ""),
        year=arguments.get("year"),
        quarter=arguments.get("quarter"),
    )


def get_company_profile_tool() -> Tool:
    return Tool(
        name="get_company_profile",
        description=(
            "Profil lengkap emiten dari IDX official: nama perusahaan, sektor/industri, "
            "kegiatan usaha, tanggal listing, papan pencatatan, alamat, kontak, "
            "daftar direksi & jabatan, komisaris (termasuk independen), "
            "dan sekretaris perusahaan. "
            "Data lebih lengkap dari yfinance karena langsung dari IDX. "
            "Gunakan untuk: 'siapa direktur BBCA?', 'ZATA listing kapan?', "
            "'komisaris independen TLKM siapa?'"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Kode emiten IDX (contoh: BBCA, ZATA, TLKM)"
                }
            },
            "required": ["ticker"]
        }
    )


async def get_company_profile(arguments: dict) -> dict:
    return fetch_company_profile(ticker=arguments.get("ticker", ""))
