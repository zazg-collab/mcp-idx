"""
IDX Official Data Tools — via curl_cffi (browser impersonation).

Mengambil data resmi dari IDX (idx.co.id) yang sebelumnya diblock Cloudflare.
curl_cffi dengan impersonate='chrome' berhasil bypass proteksi tersebut.

CATATAN PENTING:
  GetFinancialReport IDX hanya menyimpan Annual Report (Laporan Tahunan),
  BUKAN LK quarterly. TW1-TW4 di endpoint ini semua return file yang sama.
  LK quarterly (Q1-Q3) ada di sistem e-Reporting XBRL IDX yang berbeda (503).

Tools:
  - get_annual_report   : Cek Annual Report per emiten per tahun
  - get_company_profile : Profil lengkap emiten (direksi, komisaris, sekretaris)
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


# ── helpers ────────────────────────────────────────────────────────────────────

def _clean_ticker(ticker: str) -> str:
    return ticker.strip().upper().replace(".JK", "")


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


def _fmt_date(raw: str) -> Optional[str]:
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d")
    except Exception:
        return raw[:10] if raw else None


# ── 1. Annual Report ───────────────────────────────────────────────────────────

def fetch_annual_report(ticker: str, year: Optional[int] = None) -> dict:
    """
    Cek Annual Report (Laporan Tahunan) emiten dari IDX official.

    CATATAN: Endpoint IDX GetFinancialReport hanya menyimpan Annual Report,
    bukan LK quarterly. Untuk LK quarterly gunakan get_quarterly_earnings.
    """
    if not _CFFI_AVAILABLE:
        return {"error": "curl_cffi tidak terinstall. Jalankan: pip install curl_cffi"}

    ticker = _clean_ticker(ticker)
    if not _VALID_TICKER.match(ticker):
        return {"error": f"Ticker tidak valid: {ticker}"}

    current_year = datetime.now().year
    years_to_check = (
        [str(year)] if year
        else [str(current_year - i) for i in range(4)]
    )

    results = []
    for yr in years_to_check:
        # TW4 sebagai proxy Annual Report (semua TW return file yang sama)
        url = (
            f"{IDX_BASE}/GetFinancialReport"
            f"?KodeEmiten={ticker}&ReportType=LK&Year={yr}&Periode=TW4"
        )
        data = _get(url)
        count = data.get("ResultCount", 0) if data else 0

        if count == 0:
            results.append({
                "year": yr,
                "status": "NOT PUBLISHED",
                "published_date": None,
                "files": [],
            })
            continue

        row = data["Results"][0]
        attachments = row.get("Attachments", [])

        files = []
        for att in attachments:
            fname = att.get("File_Name", "")
            fpath = att.get("File_Path", "")
            fname_up = fname.upper()
            if any(k in fname_up for k in ["ESG", "SUSTAIN"]):
                category = "ESG"
            elif any(k in fname_up for k in ["ANNUAL", "TAHUNAN"]):
                category = "Annual Report"
            else:
                category = "Other"
            files.append({
                "filename": fname,
                "url": IDX_PDF_BASE + fpath if fpath else None,
                "category": category,
            })

        results.append({
            "year": yr,
            "status": "PUBLISHED",
            "published_date": _fmt_date(row.get("File_Modified", "")),
            "emiten": row.get("NamaEmiten", ticker),
            "files": files,
        })

    published = [r for r in results if r["status"] == "PUBLISHED"]
    latest = published[0] if published else None

    return {
        "ticker": ticker,
        "report_type": "Annual Report (Laporan Tahunan)",
        "note": "Untuk LK quarterly (Q1-Q3) gunakan get_quarterly_earnings atau cek Stockbit/platform broker.",
        "summary": {
            "years_checked": years_to_check,
            "total_published": len(published),
            "latest_year": latest["year"] if latest else None,
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

    efek = []
    if p.get("EfekEmiten_Saham"):    efek.append("Saham")
    if p.get("EfekEmiten_Obligasi"): efek.append("Obligasi")
    if p.get("EfekEmiten_ETF"):      efek.append("ETF")
    if p.get("EfekEmiten_EBA"):      efek.append("EBA")

    logo = p.get("Logo", "")

    direktur = [
        {
            "nama": d.get("Nama", "").strip(),
            "jabatan": d.get("Jabatan", ""),
            "afiliasi": d.get("Afiliasi", False),
        }
        for d in data.get("Direktur", [])
    ]

    komisaris = [
        {
            "nama": k.get("Nama", "").strip(),
            "jabatan": k.get("Jabatan", ""),
            "independen": k.get("Independen", False),
        }
        for k in data.get("Komisaris", [])
    ]

    sekretaris = [
        {
            "nama": s.get("Nama", "").strip(),
            "email": s.get("Email", ""),
            "telepon": s.get("Telepon", ""),
        }
        for s in data.get("Sekretaris", [])
    ]

    return {
        "ticker": ticker,
        "nama_emiten": p.get("NamaEmiten", ""),
        "kegiatan_usaha": (p.get("KegiatanUsahaUtama") or "").strip(),
        "sektor": p.get("Sektor", ""),
        "sub_sektor": p.get("SubSektor", ""),
        "industri": p.get("Industri", ""),
        "sub_industri": p.get("SubIndustri", ""),
        "papan_pencatatan": p.get("PapanPencatatan", ""),
        "tanggal_listing": _fmt_date(p.get("TanggalPencatatan", "")),
        "efek_tercatat": efek,
        "alamat": (p.get("Alamat") or "").replace("\r\n", ", ").strip(),
        "telepon": p.get("Telepon", ""),
        "email": p.get("Email", ""),
        "website": p.get("Website", ""),
        "logo_url": IDX_PDF_BASE + logo if logo else None,
        "direksi": direktur,
        "komisaris": komisaris,
        "komisaris_independen": [k for k in komisaris if k["independen"]],
        "sekretaris_perusahaan": sekretaris,
        "source": "IDX Official (idx.co.id)",
    }


# ── MCP Tool Wrappers ──────────────────────────────────────────────────────────

def get_financial_report_tool() -> Tool:
    return Tool(
        name="get_financial_report",
        description=(
            "Cek Annual Report (Laporan Tahunan) emiten dari IDX official. "
            "Tampilkan status publish, tanggal rilis, dan link PDF Annual Report per tahun. "
            "BUKAN untuk LK quarterly — endpoint IDX ini hanya menyimpan Laporan Tahunan. "
            "Untuk LK quarterly gunakan get_quarterly_earnings. "
            "Gunakan untuk: 'Annual Report ZATA 2025 sudah rilis?', "
            "'kapan BBCA publish laporan tahunan 2024?', 'download AR TLKM'"
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
                    "description": "Tahun laporan (contoh: 2025). Opsional — kalau kosong cek 4 tahun terakhir."
                }
            },
            "required": ["ticker"]
        }
    )


async def get_financial_report(arguments: dict) -> dict:
    return fetch_annual_report(
        ticker=arguments.get("ticker", ""),
        year=arguments.get("year"),
    )


def get_company_profile_tool() -> Tool:
    return Tool(
        name="get_company_profile",
        description=(
            "Profil lengkap emiten dari IDX official: nama perusahaan, sektor/industri, "
            "kegiatan usaha, tanggal listing, papan pencatatan (Utama/Pengembangan/Akselerasi), "
            "alamat, kontak, daftar direksi & jabatan, komisaris (termasuk independen), "
            "dan sekretaris perusahaan. "
            "Data lebih lengkap dari yfinance karena langsung dari IDX. "
            "Gunakan untuk: 'siapa direktur BBCA?', 'ZATA listing kapan?', "
            "'komisaris independen TLKM siapa?', 'papan pencatatan BBRI apa?'"
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
