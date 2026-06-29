"""Bulk screener tool for IDX stocks using tradingview_screener."""

import math
from typing import Any

from mcp.types import Tool


def get_bulk_screener_tool() -> Tool:
    """Get bulk screener tool definition."""
    return Tool(
        name="screen_idx_bulk",
        description=(
            "Bulk screener untuk seluruh saham IDX menggunakan TradingView data. "
            "Filter dan sortir saham berdasarkan volume, rasio volume vs rata-rata 60 hari (V60), "
            "posisi terhadap MA, perubahan harga, dan RSI. "
            "Berguna untuk menemukan kandidat saham dengan volume breakout atau setup teknikal tertentu."
        ),
        inputSchema={
            "type": "object",
            "properties": {
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

    # ── Parse arguments ───────────────────────────────────────────────────────
    sector_filter      = str(args.get("sector", "")).strip().lower()
    min_volume_m       = float(args.get("min_volume_m", 0))
    min_vol_ratio_v60  = float(args.get("min_vol_ratio_v60", 0))
    above_ma20         = bool(args.get("above_ma20", False))
    above_ma50         = bool(args.get("above_ma50", False))
    min_change_pct     = float(args.get("min_change_pct", -99))
    max_change_pct     = float(args.get("max_change_pct", 99))
    sort_by            = str(args.get("sort_by", "volume"))
    limit              = int(args.get("limit", 50))

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
        "filters_applied": {
            "sector":           sector_filter or None,
            "min_volume_m":     min_volume_m if min_volume_m > 0 else None,
            "min_vol_ratio_v60": min_vol_ratio_v60 if min_vol_ratio_v60 > 0 else None,
            "above_ma20":       above_ma20 or None,
            "above_ma50":       above_ma50 or None,
            "min_change_pct":   min_change_pct if min_change_pct > -99 else None,
            "max_change_pct":   max_change_pct if max_change_pct < 99 else None,
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
