"""
Extended Fundamental Analysis Tools
Quarterly earnings + EPS surprise, ownership/institutional holders,
corporate actions (dividends, splits), upcoming ex-dividend date.
"""

from ..utils.validators import validate_ticker
from ..utils.helpers import format_ticker
from mcp.types import Tool
import yfinance as yf
from datetime import datetime
from typing import Optional


def _ts_to_date(ts) -> Optional[str]:
    """Convert unix timestamp or None to YYYY-MM-DD string."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except Exception:
        return None


# ─── 1. Quarterly Earnings + EPS Surprise ─────────────────────────────────────

def analyze_quarterly_earnings(ticker: str) -> dict:
    """
    Quarterly earnings history: EPS actual vs estimate + surprise %.
    Gunakan ini untuk melihat apakah emiten konsisten beat/miss ekspektasi.
    """
    ticker = validate_ticker(ticker)
    ticker_jk = format_ticker(ticker)

    try:
        stock = yf.Ticker(ticker_jk)

        result = {
            "ticker": ticker.replace(".JK", ""),
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        }

        # --- EPS Surprise history ---
        eh = stock.earnings_history
        if eh is not None and not eh.empty:
            rows = []
            for qdate, row in eh.iterrows():
                eps_actual = row.get("epsActual")
                eps_est    = row.get("epsEstimate")
                surprise   = row.get("surprisePercent")
                rows.append({
                    "quarter":          str(qdate)[:10],
                    "eps_actual":       round(float(eps_actual), 4) if eps_actual is not None else None,
                    "eps_estimate":     round(float(eps_est),    4) if eps_est    is not None else None,
                    "eps_surprise":     round(float(surprise) * 100, 2) if surprise is not None else None,
                    "beat_miss":        "BEAT" if (surprise or 0) > 0 else "MISS" if (surprise or 0) < 0 else "IN LINE",
                })
            result["eps_surprise_history"] = rows[-8:]  # last 8 quarters

            # Beat rate
            beats = sum(1 for r in rows if r["beat_miss"] == "BEAT")
            result["beat_rate_pct"] = round(beats / len(rows) * 100, 1) if rows else 0
            result["beat_rate_label"] = (
                "🟢 Consistent Beater" if result["beat_rate_pct"] >= 75 else
                "🟡 Occasional Beater" if result["beat_rate_pct"] >= 50 else
                "🔴 Frequent Miss"
            )

        # --- Quarterly Income Statement (Revenue, Net Income) ---
        qi = stock.quarterly_income_stmt
        if qi is not None and not qi.empty:
            quarters = []
            for col in qi.columns[:8]:  # last 8 quarters
                rev = qi.loc["Total Revenue", col]   if "Total Revenue"   in qi.index else None
                ni  = qi.loc["Net Income",    col]   if "Net Income"      in qi.index else None
                op  = qi.loc["Operating Income", col] if "Operating Income" in qi.index else None
                quarters.append({
                    "period":           str(col)[:10],
                    "revenue":          int(rev) if rev and not (isinstance(rev, float) and rev != rev) else None,
                    "net_income":       int(ni)  if ni  and not (isinstance(ni, float)  and ni  != ni)  else None,
                    "operating_income": int(op)  if op  and not (isinstance(op, float)  and op  != op)  else None,
                })
            result["quarterly_financials"] = quarters

            # QoQ revenue growth (latest vs previous quarter)
            valid = [q for q in quarters if q["revenue"]]
            if len(valid) >= 2:
                latest, prev = valid[0]["revenue"], valid[1]["revenue"]
                result["qoq_revenue_growth"] = round((latest - prev) / prev * 100, 2) if prev else None

        return result

    except Exception as e:
        return {"error": str(e)}


# ─── 2. Ownership & Institutional Holders ─────────────────────────────────────

def analyze_ownership(ticker: str) -> dict:
    """
    Kepemilikan saham: % institusi, % insider, daftar institutional holders,
    dan info ex-dividend terdekat.
    """
    ticker = validate_ticker(ticker)
    ticker_jk = format_ticker(ticker)

    try:
        stock = yf.Ticker(ticker_jk)
        info  = stock.info

        result = {
            "ticker":        ticker.replace(".JK", ""),
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        }

        # --- Major holders summary ---
        mh = stock.major_holders
        if mh is not None and not mh.empty:
            # "Breakdown" is the DataFrame index, "Value" is the single column
            breakdown = {str(idx): mh.loc[idx, "Value"] for idx in mh.index}
            result["ownership_summary"] = {
                "insiders_pct":       round(float(breakdown.get("insidersPercentHeld", 0)) * 100, 2),
                "institutions_pct":   round(float(breakdown.get("institutionsPercentHeld", 0)) * 100, 2),
                "float_held_by_inst": round(float(breakdown.get("institutionsFloatPercentHeld", 0)) * 100, 2),
                "institutions_count": int(breakdown.get("institutionsCount", 0)),
            }

            inst_pct = result["ownership_summary"]["institutions_pct"]
            result["ownership_rating"] = (
                "🟢 High institutional interest" if inst_pct >= 20 else
                "🟡 Moderate institutional interest" if inst_pct >= 10 else
                "⚪ Low institutional coverage"
            )

        # --- Top institutional holders ---
        ih = stock.institutional_holders
        if ih is not None and not ih.empty:
            holders = []
            for _, row in ih.head(10).iterrows():
                holders.append({
                    "holder":          str(row.get("Holder", "")),
                    "pct_held":        round(float(row.get("pctHeld", 0)) * 100, 3),
                    "shares":          int(row.get("Shares", 0)),
                    "date_reported":   str(row.get("Date Reported", ""))[:10],
                    "pct_change":      round(float(row.get("pctChange", 0)) * 100, 2) if row.get("pctChange") is not None else None,
                })
            result["institutional_holders"] = holders

        # --- Upcoming dividend / ex-date ---
        dividend_info = {
            "dividend_yield_pct":   round(float(info.get("dividendYield", 0) or 0) * 100 if info.get("dividendYield", 0) and info.get("dividendYield", 0) < 1 else float(info.get("dividendYield", 0) or 0), 2),
            "last_dividend_value":  info.get("lastDividendValue"),
            "ex_dividend_date":     _ts_to_date(info.get("exDividendDate")),
            "last_dividend_date":   _ts_to_date(info.get("lastDividendDate")),
            "payout_ratio":         round(float(info.get("payoutRatio", 0)) * 100, 2) if info.get("payoutRatio") else None,
            "five_year_avg_yield":  round(float(info.get("fiveYearAvgDividendYield", 0)), 2) if info.get("fiveYearAvgDividendYield") else None,
        }

        # Check if ex-date is upcoming
        ex = dividend_info["ex_dividend_date"]
        today = datetime.now().strftime("%Y-%m-%d")
        if ex and ex >= today:
            dividend_info["upcoming_ex_dividend"] = True
            dividend_info["note"] = f"⚠️ Ex-dividend date {ex} belum lewat — beli sebelum tanggal ini untuk dapat dividen"
        else:
            dividend_info["upcoming_ex_dividend"] = False

        result["dividend_info"] = dividend_info

        return result

    except Exception as e:
        return {"error": str(e)}


# ─── 3. Corporate Actions (Dividends + Splits History) ────────────────────────

def analyze_corporate_actions(ticker: str) -> dict:
    """
    History corporate actions: semua pembayaran dividen dan stock split.
    Berguna untuk melihat pola distribusi dividen dan riwayat stock split emiten.
    """
    ticker = validate_ticker(ticker)
    ticker_jk = format_ticker(ticker)

    try:
        stock = yf.Ticker(ticker_jk)

        result = {
            "ticker":        ticker.replace(".JK", ""),
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        }

        actions = stock.actions
        if actions is None or actions.empty:
            return {**result, "message": "No corporate actions found"}

        # --- Dividends ---
        div_series = actions["Dividends"][actions["Dividends"] > 0] if "Dividends" in actions.columns else actions.__class__(dtype=float)
        if not div_series.empty:
            div_list = [
                {"date": str(d)[:10], "amount": round(float(v), 4)}
                for d, v in div_series.tail(20).items()
            ]
            result["dividend_history"] = div_list

            # Annual totals (last 3 years)
            annual = {}
            for d, v in div_series.items():
                yr = str(d)[:4]
                annual[yr] = round(annual.get(yr, 0) + float(v), 2)
            result["annual_dividends"] = dict(sorted(annual.items(), reverse=True)[:5])

            # DPS trend
            years_sorted = sorted(annual.keys(), reverse=True)
            if len(years_sorted) >= 2:
                latest_yr, prev_yr = years_sorted[0], years_sorted[1]
                if annual[prev_yr] > 0:
                    dps_growth = (annual[latest_yr] - annual[prev_yr]) / annual[prev_yr] * 100
                    result["dps_yoy_growth"] = round(dps_growth, 2)
                    result["dps_trend"] = (
                        "🟢 Increasing" if dps_growth > 5 else
                        "🟡 Stable"     if dps_growth >= -5 else
                        "🔴 Decreasing"
                    )

        # --- Stock Splits ---
        split_series = actions["Stock Splits"][actions["Stock Splits"] > 0] if "Stock Splits" in actions.columns else actions.__class__(dtype=float)
        if not split_series.empty:
            def _fmt_ratio(v: float) -> str:
                """Format split ratio. v=2.0 → '2:1' (split), v=0.5 → '1:2' (reverse split)."""
                if v >= 1:
                    return f"{int(v)}:1"
                else:
                    denom = round(1 / v)
                    return f"1:{denom} (reverse split)"

            result["stock_splits"] = [
                {"date": str(d)[:10], "ratio": _fmt_ratio(float(v))}
                for d, v in split_series.items()
            ]
        else:
            result["stock_splits"] = []
            result["split_note"] = "No stock splits on record"

        return result

    except Exception as e:
        return {"error": str(e)}


# ==================== MCP TOOL WRAPPERS ====================

def get_quarterly_earnings_tool() -> Tool:
    return Tool(
        name="get_quarterly_earnings",
        description=(
            "Quarterly earnings history dengan EPS actual vs estimate (surprise %). "
            "Tampilkan beat/miss rate, quarterly revenue & net income, dan QoQ growth. "
            "Gunakan untuk cek konsistensi emiten dalam memenuhi ekspektasi analis."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker saham IDX (contoh: BBCA, BBRI, TLKM)"
                }
            },
            "required": ["ticker"]
        }
    )


async def get_quarterly_earnings(arguments: dict) -> dict:
    return analyze_quarterly_earnings(arguments.get("ticker"))


def get_ownership_tool() -> Tool:
    return Tool(
        name="get_ownership_info",
        description=(
            "Informasi kepemilikan saham: % kepemilikan institusi & insider, "
            "daftar institutional holders, dan info ex-dividend date terdekat. "
            "Berguna untuk melihat apakah ada akumulasi institusi dan jadwal dividen."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker saham IDX (contoh: BBCA, BBRI, TLKM)"
                }
            },
            "required": ["ticker"]
        }
    )


async def get_ownership_info(arguments: dict) -> dict:
    return analyze_ownership(arguments.get("ticker"))


def get_corporate_actions_tool() -> Tool:
    return Tool(
        name="get_corporate_actions",
        description=(
            "History corporate actions emiten: semua pembayaran dividen (per tanggal & nominal), "
            "annual DPS, trend DPS YoY, dan history stock split. "
            "Gunakan untuk analisis dividend investor atau cek apakah emiten pernah split."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker saham IDX (contoh: BBCA, BBRI, TLKM)"
                }
            },
            "required": ["ticker"]
        }
    )


async def get_corporate_actions(arguments: dict) -> dict:
    return analyze_corporate_actions(arguments.get("ticker"))
