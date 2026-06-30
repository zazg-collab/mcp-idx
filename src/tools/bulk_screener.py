"""Bulk screener tool for IDX stocks using tradingview_screener."""

import math
from typing import Any

from mcp.types import Tool

# ── Index constituent lists ───────────────────────────────────────────────────

_LQ45_TICKERS = {
    "ACES", "ADRO", "AKRA", "AMRT", "ANTM", "ARTO", "ASII", "BBCA", "BBNI",
    "BBRI", "BBTN", "BELI", "BJBR", "BJTM", "BKSL", "BMRI", "BREN", "BRPT",
    "BUKA", "CPIN", "EMTK", "EXCL", "GGRM", "GOTO", "HRUM", "ICBP", "INCO",
    "INDF", "INKP", "INTP", "ITMG", "JPFA", "KLBF", "MAPI", "MBMA", "MDKA",
    "MEDC", "MIKA", "MNCN", "PGAS", "PTBA", "PTPP", "SIDO", "SMGR", "TBIG",
    "TKIM", "TLKM", "TOWR", "UNTR", "UNVR",
}

_IDX30_TICKERS = {
    "ASII", "BBCA", "BBNI", "BBRI", "BMRI", "BREN", "BUKA", "CPIN", "EMTK",
    "EXCL", "GOTO", "ICBP", "INCO", "INDF", "INKP", "INTP", "KLBF", "MAPI",
    "MDKA", "MEDC", "PGAS", "PTBA", "SMGR", "TBIG", "TLKM", "TOWR", "UNTR",
    "UNVR", "ADRO", "ANTM",
}

_IDX80_TICKERS = _LQ45_TICKERS | {
    "AGRO", "AKRA", "APEX", "ARNA", "ASRI", "AUTO", "BEEN", "BFIN", "BIRD",
    "BSDE", "BTPS", "CASS", "CBMF", "CLEO", "CMRY", "DSNG", "ELSA", "ERAL",
    "ERAA", "ESSA", "FILM", "GJTL", "HEAL", "HKMU", "HMSP", "HRTA", "ISAT",
    "ITMG", "JPFA", "LPPF", "MAPA", "MERK", "MIDI", "MMLP", "MTDL", "PNLF",
}

_KOMPAS100_TICKERS = _IDX80_TICKERS | {
    "AALI", "ABBA", "ABMM", "ADES", "AGRS", "AIMS", "AISA", "AKPI", "ALIT",
    "ALKA", "ALMI", "ALTO", "AMAG", "AMAR", "AMIN", "ANJT", "APIC", "APLN",
}

_INDEX_MAP = {
    "LQ45":      _LQ45_TICKERS,
    "IDX30":     _IDX30_TICKERS,
    "IDX80":     _IDX80_TICKERS,
    "KOMPAS100": _KOMPAS100_TICKERS,
}

# ── Template presets ──────────────────────────────────────────────────────────

_TEMPLATES = {
    "momentum": {
        "min_vol_ratio_v60": 1.5,
        "above_ma20":        True,
        "above_ma50":        True,
        "min_change_pct":    1.0,
        "sort_by":           "vol_ratio",
    },
    "breakout": {
        "min_vol_ratio_v60": 2.0,
        "above_ma20":        True,
        "min_change_pct":    2.0,
        "sort_by":           "change",
    },
    "cia_ketat": {
        "above_ma20":        True,
        "above_ma50":        True,
        "min_vol_ratio_v60": 0.5,
        "sort_by":           "vol_ratio",
    },
    "value": {
        "above_ma20":   True,
        "min_volume_m": 5,
        "sort_by":      "volume",
    },
}


def get_bulk_screener_tool() -> Tool:
    """Get bulk screener tool definition."""
    return Tool(
        name="screen_idx_bulk",
        description=(
            "Bulk screener untuk seluruh saham IDX menggunakan TradingView data. "
            "Filter dan sortir saham berdasarkan volume, rasio volume vs rata-rata 60 hari (V60), "
            "posisi terhadap MA, perubahan harga, dan RSI. "
            "Berguna untuk menemukan kandidat saham dengan volume breakout atau setup teknikal tertentu. "
            "\n\nParameter tambahan:"
            "\n- index_filter: filter ke konstituen indeks tertentu ('LQ45', 'IDX30', 'IDX80', 'KOMPAS100', atau '' = semua)."
            "\n- lq45_only: shorthand bool untuk index_filter='LQ45'."
            "\n- template: preset filter siap pakai — 'momentum' (vol tinggi+above MA+naik), "
            "'breakout' (vol 2x+naik 2%), 'cia_ketat' (setup CIA ketat), 'value' (likuiditas tinggi+above MA20). "
            "Template menjadi default; parameter individual tetap bisa di-override."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "template": {
                    "type": "string",
                    "description": (
                        "Preset filter: 'momentum' (min_vol_ratio=1.5, above_ma20+50, min_change=1%), "
                        "'breakout' (min_vol_ratio=2.0, above_ma20, min_change=2%), "
                        "'cia_ketat' (above_ma20+50, min_vol_ratio=0.5), "
                        "'value' (above_ma20, min_volume_m=5). Kosong = pakai params langsung."
                    ),
                    "enum": ["", "momentum", "breakout", "cia_ketat", "value"],
                    "default": "",
                },
                "index_filter": {
                    "type": "string",
                    "description": (
                        "Filter ke konstituen indeks tertentu. "
                        "Pilihan: 'LQ45' (~50 saham paling likuid), 'IDX30' (top 30), "
                        "'IDX80', 'KOMPAS100', '' = semua saham IDX."
                    ),
                    "enum": ["", "LQ45", "IDX30", "IDX80", "KOMPAS100"],
                    "default": "",
                },
                "lq45_only": {
                    "type": "boolean",
                    "description": "Shorthand untuk index_filter='LQ45'. Jika True, hanya tampilkan saham LQ45.",
                    "default": False,
                },
                "sector": {
                    "type": "string",
                    "description": "Filter berdasarkan sektor (substring, case-insensitive). Contoh: 'Finance', 'Energy'. Kosong = semua sektor.",
                    "default": "",
                },
                "min_volume_m": {
                    "type": "number",
                    "description": "Minimum volume hari ini dalam jutaan IDR (0 = tidak difilter). Contoh: 10 = minimal 10 juta IDR.",
                    "default": 0,
                },
                "min_vol_ratio_v60": {
                    "type": "number",
                    "description": "Minimum rasio volume hari ini vs rata-rata 60 hari (V60). 0 = tidak difilter. Contoh: 1.5 = minimal 1.5x di atas rata-rata.",
                    "default": 0,
                },
                "above_ma20": {
                    "type": "boolean",
                    "description": "Hanya tampilkan saham yang harganya di atas SMA20.",
                    "default": False,
                },
                "above_ma50": {
                    "type": "boolean",
                    "description": "Hanya tampilkan saham yang harganya di atas SMA50.",
                    "default": False,
                },
                "min_change_pct": {
                    "type": "number",
                    "description": "Minimum perubahan harga harian dalam persen. Contoh: 1.0 = hanya saham yang naik >1%.",
                    "default": -99,
                },
                "max_change_pct": {
                    "type": "number",
                    "description": "Maximum perubahan harga harian dalam persen. Contoh: 5.0 = hanya saham yang naik <5%.",
                    "default": 99,
                },
                "sort_by": {
                    "type": "string",
                    "description": "Urutan hasil: 'volume' (volume tertinggi), 'vol_ratio' (rasio V60 tertinggi), 'change' (kenaikan terbesar), 'rsi' (RSI tertinggi).",
                    "enum": ["volume", "vol_ratio", "change", "rsi"],
                    "default": "volume",
                },
                "limit": {
                    "type": "integer",
                    "description": "Jumlah maksimum hasil yang ditampilkan.",
                    "default": 50,
                },
            },
            "required": [],
        },
    )


async def screen_idx_bulk_handler(args: dict[str, Any]) -> dict[str, Any]:
    """
    Bulk screen IDX stocks using tradingview_screener.

    Args:
        args: Dictionary with optional filter/sort parameters.

    Returns:
        Dictionary with screener results and metadata.
    """
    try:
        from tradingview_screener import Query
    except ImportError:
        return {
            "error": "tradingview-screener tidak tersedia. Jalankan: pip install tradingview-screener"
        }

    # ── Resolve template defaults first ──────────────────────────────────────
    template = str(args.get("template", "")).strip().lower()
    template_defaults: dict[str, Any] = {}
    if template and template in _TEMPLATES:
        template_defaults = dict(_TEMPLATES[template])

    # Merge: template defaults → user args (user args override template)
    def _get(key: str, fallback: Any) -> Any:
        if key in args:
            return args[key]
        if key in template_defaults:
            return template_defaults[key]
        return fallback

    # ── Parse arguments ───────────────────────────────────────────────────────
    sector_filter     = str(_get("sector", "")).strip().lower()
    min_volume_m      = float(_get("min_volume_m", 0))
    min_vol_ratio_v60 = float(_get("min_vol_ratio_v60", 0))
    above_ma20        = bool(_get("above_ma20", False))
    above_ma50        = bool(_get("above_ma50", False))
    min_change_pct    = float(_get("min_change_pct", -99))
    max_change_pct    = float(_get("max_change_pct", 99))
    sort_by           = str(_get("sort_by", "volume"))
    limit             = int(_get("limit", 50))

    # ── Resolve index filter ──────────────────────────────────────────────────
    lq45_only    = bool(args.get("lq45_only", False))
    index_filter = str(args.get("index_filter", "")).strip().upper()
    if lq45_only and not index_filter:
        index_filter = "LQ45"

    allowed_tickers: set[str] | None = None
    if index_filter and index_filter in _INDEX_MAP:
        allowed_tickers = _INDEX_MAP[index_filter]

    # Clamp limit to a reasonable range
    limit = max(1, min(200, limit))

    # ── Columns to fetch ──────────────────────────────────────────────────────
    cols = [
        "close",
        "volume",
        "change",
        "average_volume_60d_calc",
        "SMA5",
        "SMA10",
        "SMA20",
        "SMA50",
        "SMA200",
        "RSI",
        "sector",
        "name",
        "market_cap_basic",
    ]

    # ── Build and execute query ───────────────────────────────────────────────
    try:
        total, df = (
            Query()
            .set_markets("indonesia")
            .select(*cols)
            .order_by("volume", ascending=False)
            .limit(1000)
            .get_scanner_data()
        )
    except Exception as exc:
        return {"error": f"Gagal mengambil data dari TradingView screener: {exc}"}

    if df is None or df.empty:
        return {"error": "Tidak ada data yang tersedia dari IDX screener"}

    # ── Build result list with filters ───────────────────────────────────────
    results = []

    for _, row in df.iterrows():
        # Ticker: strip "IDX:" prefix
        raw_ticker = str(row.get("ticker", ""))
        ticker = raw_ticker.replace("IDX:", "").strip()
        if not ticker:
            continue

        close = row.get("close") or 0
        if not close or close <= 0:
            continue

        volume     = row.get("volume") or 0
        change_pct = row.get("change") or 0
        avg_vol60  = row.get("average_volume_60d_calc")
        sma5       = row.get("SMA5")
        sma10      = row.get("SMA10")
        sma20      = row.get("SMA20")
        sma50      = row.get("SMA50")
        sma200     = row.get("SMA200")
        rsi        = row.get("RSI")
        sector     = str(row.get("sector") or "")
        name       = str(row.get("name") or "")
        market_cap = row.get("market_cap_basic")

        # ── Compute V60 ratio ─────────────────────────────────────────────
        vol_ratio_v60 = None
        avg_vol60_val = None
        if avg_vol60 is not None and not _is_nan(avg_vol60) and float(avg_vol60) > 0:
            avg_vol60_val = float(avg_vol60)
            vol_ratio_v60 = round(volume / avg_vol60_val, 2) if volume > 0 else 0.0

        # ── MA booleans ───────────────────────────────────────────────────
        is_above_ma20 = (sma20 is not None and not _is_nan(sma20) and close > float(sma20))
        is_above_ma50 = (sma50 is not None and not _is_nan(sma50) and close > float(sma50))

        # ── Volume in millions IDR ────────────────────────────────────────
        volume_idr_m = round((volume * close) / 1_000_000, 2)

        # ── Apply filters ─────────────────────────────────────────────────
        if allowed_tickers is not None and ticker not in allowed_tickers:
            continue

        if sector_filter and sector_filter not in sector.lower():
            continue

        if min_volume_m > 0 and volume_idr_m < min_volume_m:
            continue

        if min_vol_ratio_v60 > 0:
            if vol_ratio_v60 is None or vol_ratio_v60 < min_vol_ratio_v60:
                continue

        if above_ma20 and not is_above_ma20:
            continue

        if above_ma50 and not is_above_ma50:
            continue

        if change_pct < min_change_pct or change_pct > max_change_pct:
            continue

        # ── Build stock dict ──────────────────────────────────────────────
        stock = {
            "ticker":         ticker,
            "name":           name,
            "sector":         sector,
            "price":          round(float(close), 2),
            "change_pct":     round(float(change_pct), 2),
            "volume":         int(volume),
            "volume_idr_m":   volume_idr_m,
            "avg_volume_60d": int(avg_vol60_val) if avg_vol60_val is not None else None,
            "vol_ratio_v60":  vol_ratio_v60,
            "sma5":           _safe_round(sma5),
            "sma10":          _safe_round(sma10),
            "sma20":          _safe_round(sma20),
            "above_ma20":     is_above_ma20,
            "sma50":          _safe_round(sma50),
            "above_ma50":     is_above_ma50,
            "sma200":         _safe_round(sma200),
            "rsi":            _safe_round(rsi, 1),
            "market_cap_b":   round(float(market_cap) / 1_000_000_000, 1) if market_cap and not _is_nan(market_cap) else None,
        }

        results.append(stock)

    # ── Sort ──────────────────────────────────────────────────────────────────
    if sort_by == "volume":
        results.sort(key=lambda x: x["volume"], reverse=True)
    elif sort_by == "vol_ratio":
        results.sort(key=lambda x: x["vol_ratio_v60"] or 0, reverse=True)
    elif sort_by == "change":
        results.sort(key=lambda x: x["change_pct"], reverse=True)
    elif sort_by == "rsi":
        results.sort(key=lambda x: x["rsi"] or 0, reverse=True)

    # ── Truncate ──────────────────────────────────────────────────────────────
    results = results[:limit]

    # ── Build response ────────────────────────────────────────────────────────
    return {
        "total_scanned":    total,
        "total_matched":    len(results),
        "scan_info": {
            "template":     template or None,
            "index_filter": index_filter or None,
            "lq45_only":    lq45_only,
        },
        "filters_applied": {
            "sector":            sector_filter or None,
            "min_volume_m":      min_volume_m if min_volume_m > 0 else None,
            "min_vol_ratio_v60": min_vol_ratio_v60 if min_vol_ratio_v60 > 0 else None,
            "above_ma20":        above_ma20 or None,
            "above_ma50":        above_ma50 or None,
            "min_change_pct":    min_change_pct if min_change_pct > -99 else None,
            "max_change_pct":    max_change_pct if max_change_pct < 99 else None,
        },
        "sort_by":  sort_by,
        "limit":    limit,
        "stocks":   results,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_nan(value: Any) -> bool:
    """Check if value is NaN."""
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _safe_round(value: Any, decimals: int = 2) -> Any:
    """Round value if it's a valid number, else return None."""
    if value is None or _is_nan(value):
        return None
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return None
