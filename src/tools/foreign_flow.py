"""
Foreign Flow & Smart Money Analysis
Deteksi akumulasi/distribusi dari investor asing dan institusi
"""

from ..utils.yahoo import YahooFinanceClient
from ..utils.validators import validate_ticker
from ..utils.helpers import format_ticker
from mcp.types import Tool
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# Initialize API
yahoo_api = YahooFinanceClient()

_IHSG_TICKER = "^JKSE"


def _calc_relative_vs_market(ticker_jk: str, period: str) -> dict:
    """
    Bandingkan pergerakan saham vs IHSG (^JKSE) untuk periode yang sama.

    Menghasilkan:
    - relative_strength : return saham / return IHSG (>1 outperform, <1 underperform)
    - relative_volume   : vol_ratio saham / vol_ratio IHSG (>2 = saham jauh lebih aktif dari market)
    - market_direction  : arah IHSG (UP / DOWN / SIDEWAYS)
    - interpretation    : kombinasi RS + RV + market direction

    Data source: yfinance (^JKSE untuk IHSG, ticker.JK untuk saham)
    """
    try:
        stock_hist = yf.Ticker(ticker_jk).history(period=period)
        ihsg_hist  = yf.Ticker(_IHSG_TICKER).history(period=period)

        if stock_hist.empty or ihsg_hist.empty or len(stock_hist) < 10 or len(ihsg_hist) < 10:
            return {"error": "Insufficient market data"}

        # Align index ke tanggal yang ada di kedua series
        common_idx = stock_hist.index.intersection(ihsg_hist.index)
        if len(common_idx) < 10:
            return {"error": "Not enough common trading days"}

        s = stock_hist.loc[common_idx, "Close"]
        m = ihsg_hist.loc[common_idx, "Close"]

        # ── Return comparison ─────────────────────────────────────────────────
        stock_return = float((s.iloc[-1] - s.iloc[0]) / s.iloc[0] * 100)
        ihsg_return  = float((m.iloc[-1] - m.iloc[0]) / m.iloc[0] * 100)

        # RS ratio: (1 + stock_return%) / (1 + ihsg_return%) - 1
        # >0 = outperform, <0 = underperform, unit = excess return vs IHSG
        rs = round((1 + stock_return / 100) / (1 + ihsg_return / 100) - 1, 4)
        rs_pct = round(rs * 100, 2)  # dalam persen

        # ── Volume comparison ─────────────────────────────────────────────────
        sv = stock_hist.loc[common_idx, "Volume"]
        mv = ihsg_hist.loc[common_idx, "Volume"]

        sv_ma = sv.rolling(10, min_periods=5).mean()
        mv_ma = mv.rolling(10, min_periods=5).mean()

        stock_vol_ratio = float(sv.iloc[-5:].mean() / (sv_ma.iloc[-5:].mean() + 1))
        ihsg_vol_ratio  = float(mv.iloc[-5:].mean() / (mv_ma.iloc[-5:].mean() + 1))
        rel_vol = round(stock_vol_ratio / (ihsg_vol_ratio + 0.01), 2)

        # ── Market direction ──────────────────────────────────────────────────
        if ihsg_return > 1.5:
            market_dir = "UP"
        elif ihsg_return < -1.5:
            market_dir = "DOWN"
        else:
            market_dir = "SIDEWAYS"

        # ── Interpretation (berdasarkan rs_pct = excess return vs IHSG) ────────
        if market_dir == "DOWN" and stock_return > 0:
            interp = "🔥 VERY STRONG — Naik saat IHSG turun"
            signal = "STRONG_BUY"
        elif market_dir == "UP" and stock_return < 0:
            interp = "🔴 VERY WEAK — Turun saat IHSG naik"
            signal = "STRONG_SELL"
        elif rs_pct > 10:
            interp = f"🟢 OUTPERFORM +{rs_pct:.1f}% vs IHSG"
            signal = "BULLISH"
        elif rs_pct > 3:
            interp = f"🟢 SLIGHT OUTPERFORM +{rs_pct:.1f}% vs IHSG"
            signal = "BULLISH"
        elif rs_pct < -10:
            interp = f"🔴 UNDERPERFORM {rs_pct:.1f}% vs IHSG"
            signal = "BEARISH"
        elif rs_pct < -3:
            interp = f"🟠 SLIGHT UNDERPERFORM {rs_pct:.1f}% vs IHSG"
            signal = "BEARISH"
        else:
            interp = f"🟡 IN LINE ({rs_pct:+.1f}% vs IHSG)"
            signal = "NEUTRAL"

        # Relative volume context
        if rel_vol > 3:
            rv_note = f"Volume {rel_vol:.1f}x lebih aktif dari market — bandar spesifik saham ini"
        elif rel_vol > 1.5:
            rv_note = f"Volume {rel_vol:.1f}x vs market — sedikit lebih aktif"
        elif rel_vol < 0.5:
            rv_note = f"Volume {rel_vol:.1f}x vs market — saham sepi, market lebih ramai"
        else:
            rv_note = f"Volume {rel_vol:.1f}x vs market — setara kondisi market"

        # ── IHSG peak-to-current context (rolling 2y) ─────────────────────────
        ihsg_2y = yf.Ticker(_IHSG_TICKER).history(period="2y")
        stock_2y = yf.Ticker(ticker_jk).history(period="2y")
        ihsg_peak_ctx = {}
        stock_peak_ctx = {}
        if not ihsg_2y.empty:
            ihsg_peak = float(ihsg_2y["Close"].max())
            ihsg_curr = float(ihsg_2y["Close"].iloc[-1])
            ihsg_peak_date = ihsg_2y["Close"].idxmax().date().isoformat()
            ihsg_peak_ctx = {
                "peak": round(ihsg_peak, 0),
                "peak_date": ihsg_peak_date,
                "current": round(ihsg_curr, 0),
                "drawdown_from_peak_pct": round((ihsg_curr - ihsg_peak) / ihsg_peak * 100, 2),
            }
        if not stock_2y.empty:
            s2_peak = float(stock_2y["Close"].max())
            s2_curr = float(stock_2y["Close"].iloc[-1])
            s2_peak_date = stock_2y["Close"].idxmax().date().isoformat()
            stock_peak_ctx = {
                "peak": round(s2_peak, 2),
                "peak_date": s2_peak_date,
                "current": round(s2_curr, 2),
                "drawdown_from_peak_pct": round((s2_curr - s2_peak) / s2_peak * 100, 2),
            }

        return {
            "market_ticker": "IHSG (^JKSE)",
            "comparison_period": period,
            "note": f"Return comparison untuk {period} terakhir. Lihat peak_context untuk gambaran dari puncak.",
            "stock_return_pct": round(stock_return, 2),
            "ihsg_return_pct": round(ihsg_return, 2),
            "relative_strength_pct": rs_pct,
            "rs_label": "OUTPERFORM" if rs_pct > 3 else "UNDERPERFORM" if rs_pct < -3 else "IN_LINE",
            "stock_vol_ratio": round(stock_vol_ratio, 2),
            "ihsg_vol_ratio": round(ihsg_vol_ratio, 2),
            "relative_volume": rel_vol,
            "rv_note": rv_note,
            "market_direction": market_dir,
            "interpretation": interp,
            "signal": signal,
            "ihsg_peak_context": ihsg_peak_ctx,
            "stock_peak_context": stock_peak_ctx,
        }

    except Exception as e:
        return {"error": f"Market comparison failed: {e}"}


def analyze_foreign_flow(ticker: str, period: str = "1mo") -> dict:
    """
    Analisis Smart Money Proxy berdasarkan volume-price action.
    
    DISCLAIMER: Ini BUKAN data foreign net buy/sell dari BEI.
    Data institutional_holders dari yfinance sering kosong untuk saham IDX.
    Analisis ini lebih fokus ke volume-price pattern untuk deteksi
    akumulasi/distribusi, bukan actual foreign flow.
    
    Untuk real foreign flow, gunakan data dari:
    - RTI Business (broker summary)
    - IDX website (foreign ownership data)
    - Bloomberg/Reuters terminal
    
    Args:
        ticker: Stock ticker (e.g., 'BBRI', 'BBCA')
        period: Period untuk analisis volume pattern
        
    Returns:
        Dictionary dengan analisis smart money proxy
    """
    ticker = validate_ticker(ticker)
    ticker_jk = format_ticker(ticker)  # Add .JK suffix
    
    try:
        # Get stock object
        stock = yf.Ticker(ticker_jk)
        info = stock.info
        
        # Get institutional holders data
        institutional = stock.institutional_holders
        major_holders = stock.major_holders
        
        # Get historical data untuk volume analysis
        hist_data = yahoo_api.get_historical_data(ticker, period=period)
        
        if 'error' in hist_data or 'data' not in hist_data:
            return {"error": "No historical data available"}
        
        # Convert to DataFrame
        hist = pd.DataFrame(hist_data['data'])
        
        if hist.empty:
            return {"error": "No historical data available"}
        
        # Ensure proper column names (capitalize)
        hist.columns = [col.capitalize() for col in hist.columns]
        
        # Calculate volume metrics (with division by zero guard)
        avg_volume = hist['Volume'].mean()
        recent_volume = hist['Volume'].tail(5).mean()
        # Guard: avoid division by zero
        if avg_volume > 0:
            volume_trend = ((recent_volume - avg_volume) / avg_volume) * 100
        else:
            volume_trend = 0.0
        
        # Analyze price-volume correlation
        hist['Returns'] = hist['Close'].pct_change()
        hist['Volume_Change'] = hist['Volume'].pct_change()
        
        # Detect accumulation/distribution
        # Accumulation: Price up + Volume up
        # Distribution: Price down + Volume up
        accumulation_days = len(hist[(hist['Returns'] > 0) & (hist['Volume'] > avg_volume)])
        distribution_days = len(hist[(hist['Returns'] < 0) & (hist['Volume'] > avg_volume)])
        
        # Foreign ownership data
        insiders_pct = info.get('heldPercentInsiders', 0) * 100
        institutions_pct = info.get('heldPercentInstitutions', 0) * 100
        float_institutions_pct = info.get('institutionsFloatPercentHeld', 0) * 100
        institutions_count = info.get('institutionsCount', 0)
        
        # Analyze institutional changes
        foreign_flow_trend = "Unknown"
        if institutional is not None and not institutional.empty:
            latest_change = institutional['pctChange'].iloc[0] if 'pctChange' in institutional.columns else 0
            if latest_change > 0.05:
                foreign_flow_trend = "🟢 Strong Accumulation"
            elif latest_change > 0:
                foreign_flow_trend = "🟢 Accumulation"
            elif latest_change < -0.05:
                foreign_flow_trend = "🔴 Strong Distribution"
            elif latest_change < 0:
                foreign_flow_trend = "🔴 Distribution"
            else:
                foreign_flow_trend = "⚪ Neutral"
        
        # Calculate smart money confidence (ADAPTED FOR IDX MARKET)
        # Di pasar Indonesia, fokus ke volume-price action, bukan institutional ownership
        smart_money_score = 0
        
        # Factor 1: Accumulation vs Distribution pattern (max 35 points) - MOST IMPORTANT for IDX
        total_active_days = accumulation_days + distribution_days
        if total_active_days > 0:
            acc_ratio = accumulation_days / total_active_days
            if acc_ratio > 0.7:  # Strong accumulation dominance
                smart_money_score += 35
            elif acc_ratio > 0.55:  # Moderate accumulation
                smart_money_score += 25
            elif acc_ratio > 0.45:  # Balanced
                smart_money_score += 15
            elif acc_ratio > 0.3:  # Moderate distribution
                smart_money_score += 5
            else:  # Strong distribution - PENALIZE
                smart_money_score -= 10
        
        # Factor 2: Volume trend (max 30 points) - Critical for bandar detection
        if volume_trend > 100:  # Massive volume spike
            smart_money_score += 30
        elif volume_trend > 50:
            smart_money_score += 25
        elif volume_trend > 20:
            smart_money_score += 20
        elif volume_trend > 0:
            smart_money_score += 10
        elif volume_trend > -20:
            smart_money_score += 5
        elif volume_trend > -50:
            smart_money_score -= 5  # Penalize decreasing volume
        else:
            smart_money_score -= 15  # Heavy penalty for volume dry up
        
        # Factor 3: Price-Volume confirmation (max 25 points)
        # Di IDX, harga naik + volume naik = bandar aktif
        # Guard: avoid division by zero
        first_close = hist['Close'].iloc[0]
        if first_close > 0:
            price_change = (hist['Close'].iloc[-1] - first_close) / first_close * 100
        else:
            price_change = 0.0
        if price_change > 0 and volume_trend > 0:
            # Bullish confirmation - price up, volume up
            smart_money_score += 25
        elif price_change > 0 and volume_trend < 0:
            # Suspicious - price up tapi volume turun (weak rally)
            smart_money_score += 5
        elif price_change < 0 and volume_trend > 0:
            # Distribution sign - price down, volume up
            smart_money_score += 0
        else:
            # Price down, volume down - bandar cabut
            smart_money_score -= 10
        
        # Factor 4: Foreign ownership (max 10 points) - Less weight for IDX
        # Di IDX, institutional data dari Yahoo kurang reliable
        if institutions_pct > 20:
            smart_money_score += 10
        elif institutions_pct > 10:
            smart_money_score += 5
        elif institutions_pct > 5:
            smart_money_score += 2
        
        # Clamp score to 0-100
        smart_money_score = max(0, min(100, smart_money_score))
        
        # Determine rating (adjusted thresholds for IDX)
        if smart_money_score >= 70:
            rating = "🔥 VERY STRONG - Bandar aktif akumulasi"
        elif smart_money_score >= 50:
            rating = "🟢 STRONG - Ada tanda akumulasi"
        elif smart_money_score >= 35:
            rating = "🟡 MODERATE - Mixed signals"
        elif smart_money_score >= 20:
            rating = "🟠 WEAK - Hati-hati distribusi"
        else:
            rating = "🔴 VERY WEAK - Kemungkinan bandar cabut"
        
        return {
            "ticker": ticker.replace('.JK', ''),
            "analysis_period": period,
            "data_source": "yfinance (proxy only, not real BEI foreign flow)",
            "institutional_proxy": {
                "note": "Data ini dari yfinance, sering kosong/tidak akurat untuk IDX",
                "insiders_percent": round(insiders_pct, 2),
                "institutions_percent": round(institutions_pct, 2),
                "float_institutions_percent": round(float_institutions_pct, 2),
                "institutions_count": int(institutions_count)
            },
            "volume_flow_analysis": {
                "trend": foreign_flow_trend,
                "accumulation_days": accumulation_days,
                "distribution_days": distribution_days,
                "net_pattern": "ACCUMULATION" if accumulation_days > distribution_days else "DISTRIBUTION"
            },
            "volume_metrics": {
                "average_volume": int(avg_volume),
                "recent_volume": int(recent_volume),
                "volume_trend_pct": round(volume_trend, 2),
                "volume_status": "🔥 High" if volume_trend > 20 else "🟢 Normal" if volume_trend > -20 else "🔴 Low"
            },
            "smart_money_proxy": {
                "note": "Skor berdasarkan volume-price action, BUKAN actual foreign flow",
                "score": smart_money_score,
                "rating": rating,
                "confidence": "HIGH" if smart_money_score >= 60 else "MODERATE" if smart_money_score >= 40 else "LOW"
            },
            "interpretation": {
                "ownership_level": "High" if institutions_pct > 30 else "Moderate" if institutions_pct > 15 else "Low",
                "institutional_interest": "Strong" if institutions_count > 200 else "Moderate" if institutions_count > 100 else "Weak",
                "pattern": "Bullish" if accumulation_days > distribution_days * 1.2 else "Bearish" if distribution_days > accumulation_days * 1.2 else "Neutral"
            }
        }
        
    except Exception as e:
        return {"error": str(e)}


def get_tick_size(price: float) -> int:
    """
    Get tick size (fraksi harga) berdasarkan harga saham IDX.
    
    Aturan Tick Size IDX (Peraturan II-A):
    - Harga < 200: tick = 1
    - Harga 200 - < 500: tick = 2
    - Harga 500 - < 2000: tick = 5
    - Harga 2000 - < 5000: tick = 10
    - Harga >= 5000: tick = 25
    
    Args:
        price: Stock price
        
    Returns:
        Tick size in rupiah
    """
    if price < 200:
        return 1
    elif price < 500:
        return 2
    elif price < 2000:
        return 5
    elif price < 5000:
        return 10
    else:
        return 25


def round_to_tick(price: float, tick_size: int, direction: str = "nearest") -> float:
    """
    Round harga ke fraksi harga (tick size) terdekat.
    
    Args:
        price: Raw price to round
        tick_size: Tick size for this price level
        direction: "nearest", "up" (ceiling), or "down" (floor)
        
    Returns:
        Price rounded to valid tick
    """
    if tick_size <= 0:
        return price
    
    if direction == "up":
        # Round up (for ARA)
        return float(((price + tick_size - 1) // tick_size) * tick_size)
    elif direction == "down":
        # Round down (for ARB)
        return float((price // tick_size) * tick_size)
    else:
        # Round to nearest
        return float(round(price / tick_size) * tick_size)


def get_ara_arb_limit(price: float, is_fca: bool = False, is_ppk: bool = False) -> dict:
    """
    Hitung batas ARA/ARB berdasarkan harga saham (aturan IDX).
    UPDATED: Support tick size, FCA board, dan floor price.
    
    Papan Reguler (default):
    - Harga < 200: ±35%
    - Harga 200-5000: ±25%  
    - Harga >5000: ±20%
    
    Papan Pemantauan Khusus / FCA (Full Call Auction):
    - Semua harga: ±10% (sejak Maret 2024)
    
    Floor Price:
    - Papan Reguler: Rp 50 (gocap)
    - Papan PPK: Rp 1
    
    Args:
        price: Current stock price
        is_fca: True jika saham dalam papan pemantauan khusus (Full Call Auction)
        is_ppk: True jika saham di papan pengembangan (floor Rp1)
        
    Returns:
        Dictionary dengan ara_limit, arb_limit, dan percentage
    """
    # Determine floor price
    floor_price = 1.0 if is_ppk else 50.0
    
    # FCA board: flat ±10%
    if is_fca:
        ara_pct = 0.10
        arb_pct = 0.10
        board_type = "FCA"
    else:
        # Regular board: percentage based on price
        if price < 200:
            ara_pct = 0.35
            arb_pct = 0.35
        elif price <= 5000:
            ara_pct = 0.25
            arb_pct = 0.25
        else:
            ara_pct = 0.20
            arb_pct = 0.20
        board_type = "REGULAR"
    
    # Calculate raw ARA/ARB prices
    raw_ara = price * (1 + ara_pct)
    raw_arb = price * (1 - arb_pct)
    
    # Get tick sizes for ARA and ARB price levels
    ara_tick = get_tick_size(raw_ara)
    arb_tick = get_tick_size(raw_arb)
    
    # Round to valid tick prices
    # ARA: round DOWN (conservative, real ARA is ceiling of calculation)
    # ARB: round UP (conservative, real ARB is floor of calculation)
    ara_price = round_to_tick(raw_ara, ara_tick, direction="down")
    arb_price = round_to_tick(raw_arb, arb_tick, direction="up")
    
    # Apply floor price for ARB
    arb_price = max(arb_price, floor_price)
    
    # Handle gocap special case
    is_gocap = price <= 50
    if is_gocap and not is_ppk:
        arb_price = max(arb_price, 50.0)  # Cannot go below 50 on regular board
    
    return {
        "ara_price": ara_price,
        "arb_price": arb_price,
        "ara_percentage": ara_pct * 100,
        "arb_percentage": arb_pct * 100,
        "board_type": board_type,
        "tick_size_ara": ara_tick,
        "tick_size_arb": arb_tick,
        "floor_price": floor_price,
        "is_gocap": is_gocap,
        "is_fca": is_fca
    }


def detect_ara_arb_pattern(hist: pd.DataFrame, is_fca: bool = False) -> dict:
    """
    Detect ARA/ARB patterns dalam data historis.
    Di IDX, saham yang sering ARA = momentum kuat (bandar pump)
    Saham yang sering ARB = panic / markdown
    
    UPDATED: Now supports FCA board detection and proper tick-based limits.
    
    Args:
        hist: DataFrame dengan OHLCV data
        is_fca: True jika saham dalam papan FCA (±10% limit)
        
    Returns:
        Dictionary dengan ARA/ARB analysis
    """
    ara_days = 0
    arb_days = 0
    near_ara_days = 0  # Close to ARA (>90% of limit)
    near_arb_days = 0
    
    for i in range(1, len(hist)):
        prev_close = hist['Close'].iloc[i-1]
        curr_high = hist['High'].iloc[i]
        curr_low = hist['Low'].iloc[i]
        
        # Guard division by zero
        if prev_close <= 0:
            continue
        
        limits = get_ara_arb_limit(prev_close, is_fca=is_fca)
        ara_pct = limits['ara_percentage']
        arb_pct = limits['arb_percentage']
        
        daily_high_pct = ((curr_high - prev_close) / prev_close) * 100
        daily_low_pct = ((curr_low - prev_close) / prev_close) * 100
        
        # Check if hit ARA (using actual percentage, not hardcoded)
        if daily_high_pct >= ara_pct * 0.95:  # Within 5% of ARA
            if daily_high_pct >= ara_pct * 0.99:
                ara_days += 1
            else:
                near_ara_days += 1
        
        # Check if hit ARB
        if daily_low_pct <= -arb_pct * 0.95:
            if daily_low_pct <= -arb_pct * 0.99:
                arb_days += 1
            else:
                near_arb_days += 1
    
    # Determine pattern
    if ara_days >= 3:
        pattern = "🚀 STRONG MOMENTUM - Multiple ARA hits"
    elif ara_days >= 1:
        pattern = "📈 BULLISH MOMENTUM - ARA detected"
    elif arb_days >= 2:
        pattern = "⚠️ PANIC SELLING - Multiple ARB hits"
    elif arb_days >= 1:
        pattern = "📉 BEARISH - ARB detected"
    elif near_ara_days >= 2:
        pattern = "🟢 Near ARA - Strong buying"
    elif near_arb_days >= 2:
        pattern = "🔴 Near ARB - Strong selling"
    else:
        pattern = "⚪ Normal trading range"
    
    return {
        "ara_hits": ara_days,
        "arb_hits": arb_days,
        "near_ara": near_ara_days,
        "near_arb": near_arb_days,
        "pattern": pattern,
        "is_volatile": (ara_days + arb_days) >= 2,
        "board_type": "FCA" if is_fca else "REGULAR"
    }


def _calc_obv(hist: pd.DataFrame) -> pd.Series:
    """On-Balance Volume — kumulatif volume diarahkan oleh close vs prev close."""
    closes  = hist['Close'].values
    volumes = hist['Volume'].values
    obv = [0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=hist.index)


def _calc_cmf(hist: pd.DataFrame, window: int = 20) -> pd.Series:
    """Chaikin Money Flow — pressure beli/jual -1 s/d +1."""
    clv = ((hist['Close'] - hist['Low']) - (hist['High'] - hist['Close'])) / (
        hist['High'] - hist['Low'] + 1e-9
    )
    mfv = clv * hist['Volume']
    return mfv.rolling(window, min_periods=5).sum() / hist['Volume'].rolling(window, min_periods=5).sum()


def _calc_mfi(hist: pd.DataFrame, window: int = 14) -> pd.Series:
    """Money Flow Index — RSI berbasis volume-weighted (0-100)."""
    tp = (hist['High'] + hist['Low'] + hist['Close']) / 3
    mf = tp * hist['Volume']
    pos = mf.where(tp > tp.shift(1), 0)
    neg = mf.where(tp < tp.shift(1), 0)
    pos_sum = pos.rolling(window, min_periods=5).sum()
    neg_sum = neg.rolling(window, min_periods=5).sum()
    mfr = pos_sum / (neg_sum + 1e-9)
    return 100 - (100 / (1 + mfr))


def _calc_vwap(hist: pd.DataFrame) -> pd.Series:
    """VWAP harian — rata-rata harga tertimbang volume (rolling 20 bar)."""
    tp = (hist['High'] + hist['Low'] + hist['Close']) / 3
    cum_tpv = (tp * hist['Volume']).rolling(20, min_periods=5).sum()
    cum_vol = hist['Volume'].rolling(20, min_periods=5).sum()
    return cum_tpv / (cum_vol + 1e-9)


def _detect_divergence(
    hist: pd.DataFrame,
    obv_series: pd.Series,
    cmf_series: pd.Series,
    mfi_series: pd.Series,
    window: int = 10,
) -> dict:
    """
    Deteksi divergence antara price dan money flow indicators.

    Bullish divergence  : price ↓ tapi indikator ↑ → akumulasi tersembunyi
    Bearish divergence  : price ↑ tapi indikator ↓ → distribusi tersembunyi
    Hidden bull div     : price ↑ (higher low) tapi indikator ↓ → trend lanjut naik
    Hidden bear div     : price ↓ (lower high) tapi indikator ↑ → trend lanjut turun

    Metode: bandingkan rata-rata separuh pertama vs separuh kedua dari window bars.
    """
    n = min(window * 2, len(hist))
    if n < 10:
        return {"detected": False, "signals": [], "summary": "Insufficient data"}

    chunk = hist.tail(n)
    half  = n // 2

    # Price direction
    price_early  = chunk['Close'].iloc[:half].mean()
    price_recent = chunk['Close'].iloc[half:].mean()
    price_up = price_recent > price_early * 1.005   # >0.5% threshold
    price_down = price_recent < price_early * 0.995

    # OBV direction
    obv_chunk  = obv_series.iloc[-n:]
    obv_early  = obv_chunk.iloc[:half].mean()
    obv_recent = obv_chunk.iloc[half:].mean()
    obv_up   = obv_recent > obv_early * 1.02
    obv_down = obv_recent < obv_early * 0.98

    # CMF direction (mean of period)
    cmf_chunk  = cmf_series.iloc[-n:].dropna()
    if len(cmf_chunk) >= 4:
        cmf_early  = cmf_chunk.iloc[:len(cmf_chunk)//2].mean()
        cmf_recent = cmf_chunk.iloc[len(cmf_chunk)//2:].mean()
        cmf_up   = cmf_recent > cmf_early + 0.03
        cmf_down = cmf_recent < cmf_early - 0.03
    else:
        cmf_up = cmf_down = False

    # MFI direction
    mfi_chunk  = mfi_series.iloc[-n:].dropna()
    if len(mfi_chunk) >= 4:
        mfi_early  = mfi_chunk.iloc[:len(mfi_chunk)//2].mean()
        mfi_recent = mfi_chunk.iloc[len(mfi_chunk)//2:].mean()
        mfi_up   = mfi_recent > mfi_early + 3
        mfi_down = mfi_recent < mfi_early - 3
    else:
        mfi_up = mfi_down = False

    signals = []

    # ── Bearish divergence: price ↑ tapi indikator ↓ ────────────────────────
    if price_up:
        if obv_down:
            signals.append({
                "type": "BEARISH",
                "indicator": "OBV",
                "detail": "Harga naik tapi OBV turun — volume tidak konfirmasi rally",
                "severity": "HIGH",
            })
        if cmf_down:
            signals.append({
                "type": "BEARISH",
                "indicator": "CMF",
                "detail": "Harga naik tapi CMF turun — tekanan beli melemah",
                "severity": "MODERATE",
            })
        if mfi_down:
            signals.append({
                "type": "BEARISH",
                "indicator": "MFI",
                "detail": "Harga naik tapi MFI turun — money flow melemah",
                "severity": "MODERATE",
            })

    # ── Bullish divergence: price ↓ tapi indikator ↑ ────────────────────────
    if price_down:
        if obv_up:
            signals.append({
                "type": "BULLISH",
                "indicator": "OBV",
                "detail": "Harga turun tapi OBV naik — ada akumulasi tersembunyi",
                "severity": "HIGH",
            })
        if cmf_up:
            signals.append({
                "type": "BULLISH",
                "indicator": "CMF",
                "detail": "Harga turun tapi CMF naik — tekanan beli diam-diam meningkat",
                "severity": "MODERATE",
            })
        if mfi_up:
            signals.append({
                "type": "BULLISH",
                "indicator": "MFI",
                "detail": "Harga turun tapi MFI naik — smart money mulai masuk",
                "severity": "MODERATE",
            })

    bullish_count = sum(1 for s in signals if s["type"] == "BULLISH")
    bearish_count = sum(1 for s in signals if s["type"] == "BEARISH")
    high_count    = sum(1 for s in signals if s["severity"] == "HIGH")

    if not signals:
        summary = "✅ No divergence — price dan indikator konfirmasi satu sama lain"
        bias = "CONFIRMED"
    elif bullish_count > bearish_count:
        summary = f"🟢 BULLISH DIVERGENCE ({bullish_count} signal) — potensi reversal naik atau akumulasi"
        bias = "BULLISH_DIV"
    elif bearish_count > bullish_count:
        summary = f"🔴 BEARISH DIVERGENCE ({bearish_count} signal) — waspadai distribusi atau reversal turun"
        bias = "BEARISH_DIV"
    else:
        summary = "🟡 MIXED signals — konflik antara indikator"
        bias = "MIXED"

    return {
        "detected": len(signals) > 0,
        "bias": bias,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "high_severity_count": high_count,
        "signals": signals,
        "summary": summary,
        "window_bars": n,
    }


def _money_flow_signal(cmf: float, mfi: float, obv_trend_pct: float, vwap_dev_pct: float) -> dict:
    """
    Composite money flow signal dari 4 indikator.
    Score: -2 (strong sell) s/d +2 (strong buy) per indikator → total -8 s/d +8.
    """
    score = 0

    # CMF: >0.05 = buying pressure, <-0.05 = selling pressure
    if cmf > 0.15:   score += 2
    elif cmf > 0.05: score += 1
    elif cmf < -0.15: score -= 2
    elif cmf < -0.05: score -= 1

    # MFI: >60 = bullish, <40 = bearish, >80 = overbought, <20 = oversold
    if mfi > 80:     score += 1   # Overbought (still bullish tapi hati2)
    elif mfi > 60:   score += 2
    elif mfi < 20:   score -= 1   # Oversold (masih bearish tapi potensial reversal)
    elif mfi < 40:   score -= 2

    # OBV trend: naik = akumulasi, turun = distribusi
    if obv_trend_pct > 10:   score += 2
    elif obv_trend_pct > 2:  score += 1
    elif obv_trend_pct < -10: score -= 2
    elif obv_trend_pct < -2:  score -= 1

    # VWAP deviation: harga di atas VWAP = demand kuat
    if vwap_dev_pct > 3:    score += 2
    elif vwap_dev_pct > 1:  score += 1
    elif vwap_dev_pct < -3: score -= 2
    elif vwap_dev_pct < -1: score -= 1

    # Normalize ke -100..+100
    normalized = round((score / 8) * 100, 1)

    if score >= 5:     label = "🔥 STRONG BUY — Uang masuk deras"
    elif score >= 2:   label = "🟢 BUY — Tekanan beli dominan"
    elif score >= -1:  label = "🟡 NEUTRAL — Flow seimbang"
    elif score >= -4:  label = "🟠 SELL — Tekanan jual dominan"
    else:              label = "🔴 STRONG SELL — Uang keluar deras"

    return {"score": normalized, "label": label, "raw_score": score}


def _score_phase_window(window: pd.DataFrame) -> dict:
    """
    Hitung phase scores untuk satu window DataFrame yang sudah memiliki
    kolom: Returns, Volume_Ratio, Close_Position, Daily_Range, Avg_Range, Price_MA, MA_Slope.

    Returns dict: phase, scores, price_trend, confidence.
    """
    if len(window) < 5:
        return {"phase": "UNKNOWN", "scores": {}, "price_trend": 0.0, "confidence": "LOW"}

    ma_slope = window['MA_Slope'].iloc[-1] * 100 if not pd.isna(window['MA_Slope'].iloc[-1]) else 0
    current_vs_ma = window['Close'].iloc[-1] > window['Price_MA'].iloc[-1]

    first_price = window['Close'].iloc[0]
    price_trend = ((window['Close'].iloc[-1] - first_price) / first_price * 100) if first_price > 0 else 0.0

    acc = dist = markup = markdown = 0.0
    consecutive_down = 0

    for _, row in window.iterrows():
        ret       = row['Returns'] * 100 if not pd.isna(row['Returns']) else 0
        vol_ratio = row['Volume_Ratio'] if not pd.isna(row['Volume_Ratio']) else 1.0
        close_pos = row['Close_Position'] if not pd.isna(row['Close_Position']) else 0.5
        d_range   = row['Daily_Range'] if not pd.isna(row['Daily_Range']) else 2.0
        avg_range = row['Avg_Range'] if not pd.isna(row['Avg_Range']) else 2.0
        above_ma  = row['Close'] > row['Price_MA'] if not pd.isna(row['Price_MA']) else True

        if vol_ratio > 1.2:
            vol_regime, weight = 'HIGH', 1.0
        elif vol_ratio < 0.8:
            vol_regime, weight = 'LOW', 0.5
        else:
            vol_regime, weight = 'NEUTRAL', 0.35

        # Accumulation
        if vol_regime == 'HIGH' and -2 < ret < 2:
            acc += 1.0
        elif vol_regime == 'NEUTRAL' and d_range < avg_range and close_pos > 0.6 and ret > -1:
            acc += 0.5
        elif vol_regime in ('HIGH', 'NEUTRAL') and -3 < ret < 0 and close_pos > 0.7:
            acc += weight * 0.7

        # Markup
        if vol_regime == 'HIGH' and ret > 2:
            markup += 1.0
        elif vol_regime == 'NEUTRAL' and ret > 1.5:
            markup += 0.4
        elif ret > 0.5 and close_pos > 0.8:
            markup += weight * 0.5

        # Distribution
        if vol_regime == 'HIGH' and ret < -2 and above_ma:
            dist += 1.0
        elif vol_regime == 'HIGH' and close_pos < 0.3:
            dist += 0.7
        elif vol_regime == 'NEUTRAL' and close_pos < 0.3 and above_ma:
            dist += 0.3

        # Markdown
        if ret < -0.5:
            consecutive_down += 1
        else:
            consecutive_down = 0

        if vol_regime == 'LOW' and ret < -2 and not above_ma:
            markdown += 1.0
        elif vol_regime == 'HIGH' and ret < -3 and not above_ma:
            markdown += 1.2
        elif consecutive_down >= 2 and not above_ma:
            markdown += 0.6
        elif consecutive_down >= 3:
            markdown += 0.8
        elif not above_ma and ma_slope < -0.5 and ret < -1:
            markdown += 0.5

        if close_pos < 0.2 and ret < 0:
            markdown += 0.3

    # Bonus confirmations
    if not current_vs_ma and price_trend < -5 and ma_slope < 0:
        markdown += 2.0
    if current_vs_ma and price_trend > 5 and ma_slope > 0:
        markup += 1.5

    scores = {
        'ACCUMULATION': round(acc, 1),
        'MARKUP':       round(markup, 1),
        'DISTRIBUTION': round(dist, 1),
        'MARKDOWN':     round(markdown, 1),
    }
    max_score    = max(scores.values())
    second_best  = sorted(scores.values(), reverse=True)[1]
    margin       = max_score - second_best
    total_score  = sum(scores.values())
    margin_pct   = (margin / total_score * 100) if total_score > 0 else 0

    if max_score < 2 or (margin < 2 and margin_pct < 25):
        phase = 'TRANSITION'
    else:
        phase = max(scores, key=scores.get)

    confidence = (
        "HIGH"     if max_score >= 5 and margin >= 3 else
        "MODERATE" if max_score >= 3 and margin >= 2 else
        "LOW"
    )

    return {
        "phase":       phase,
        "scores":      scores,
        "price_trend": round(price_trend, 2),
        "confidence":  confidence,
    }


def _build_phase_history(hist: pd.DataFrame) -> list[dict]:
    """
    Bagi hist menjadi 3 window (~early / mid / recent) dan deteksi fase tiap window.
    Gunakan untuk melihat trajectory fase: ACCUMULATION → MARKUP → DISTRIBUTION dst.
    """
    n = len(hist)
    if n < 30:
        return []

    # Bagi ke 3 segmen berukuran sama
    seg = n // 3
    windows = [
        ("early",  hist.iloc[:seg]),
        ("mid",    hist.iloc[seg: seg * 2]),
        ("recent", hist.iloc[seg * 2:]),
    ]

    history = []
    _phase_emoji = {
        "ACCUMULATION": "🟢",
        "MARKUP":       "🔥",
        "DISTRIBUTION": "🔴",
        "MARKDOWN":     "⚪",
        "TRANSITION":   "🟡",
        "UNKNOWN":      "❓",
    }

    for label, window in windows:
        result = _score_phase_window(window)
        start_date = str(window.index[0])[:10]  if hasattr(window.index[0], 'date') else str(window.index[0])[:10]
        end_date   = str(window.index[-1])[:10] if hasattr(window.index[-1], 'date') else str(window.index[-1])[:10]
        phase = result["phase"]
        history.append({
            "window":      label,
            "date_range":  f"{start_date} → {end_date}",
            "phase":       phase,
            "emoji":       _phase_emoji.get(phase, "❓"),
            "price_trend": result["price_trend"],
            "confidence":  result["confidence"],
            "scores":      result["scores"],
        })

    # Trajectory string: "🟢 ACCUM → 🔥 MARKUP → 🔴 DIST"
    trajectory = " → ".join(
        f"{h['emoji']} {h['phase']}" for h in history
    )

    # Analisis momentum: apakah fase sedang membaik atau memburuk?
    phase_rank = {"ACCUMULATION": 1, "MARKUP": 2, "TRANSITION": 1.5,
                  "DISTRIBUTION": 3, "MARKDOWN": 4, "UNKNOWN": 0}
    ranks = [phase_rank.get(h["phase"], 0) for h in history]
    if ranks[-1] > ranks[0]:
        momentum = "DETERIORATING"   # Makin ke kanan makin jelek (menuju markdown)
    elif ranks[-1] < ranks[0]:
        momentum = "IMPROVING"       # Makin ke kanan makin bagus (menuju markup)
    else:
        momentum = "STABLE"

    return {
        "windows":    history,
        "trajectory": trajectory,
        "momentum":   momentum,
        "note": (
            "IMPROVING = fase membaik (menuju akumulasi/markup). "
            "DETERIORATING = fase memburuk (menuju distribusi/markdown)."
        ),
    }


def analyze_bandarmology(ticker: str, period: str = "3mo") -> dict:
    """
    Analisis pola akumulasi/distribusi bandar berdasarkan price-volume action.
    OPTIMIZED FOR IDX MARKET.

    Indikator:
    - Phase detection: ACCUMULATION / MARKUP / DISTRIBUTION / MARKDOWN
    - OBV  : On-Balance Volume (kumulatif arah volume)
    - CMF  : Chaikin Money Flow (-1..+1, pressure beli/jual)
    - MFI  : Money Flow Index (0-100, RSI berbasis volume)
    - VWAP : harga vs rata-rata tertimbang volume (proximity signal)
    - ARA/ARB detection: unique untuk pasar Indonesia

    Args:
        ticker: Stock ticker
        period: Analysis period

    Returns:
        Dictionary dengan analisis bandarmology + money_flow_indicators
    """
    ticker = validate_ticker(ticker)

    try:
        hist_data = yahoo_api.get_historical_data(ticker, period=period)

        if 'error' in hist_data or 'data' not in hist_data:
            return {"error": "No historical data available"}

        # Convert to DataFrame
        hist = pd.DataFrame(hist_data['data'])
        
        if hist.empty or len(hist) < 20:
            return {"error": "Insufficient data for bandarmology analysis"}
        
        # Ensure proper column names
        hist.columns = [col.capitalize() for col in hist.columns]
        
        # Calculate indicators with adaptive window
        data_len = len(hist)
        ma_window = min(20, max(5, data_len // 2))  # Adaptive: min 5, max 20
        
        hist['Returns'] = hist['Close'].pct_change()
        hist['Volume_MA'] = hist['Volume'].rolling(ma_window, min_periods=3).mean()
        hist['Volume_Ratio'] = hist['Volume'] / hist['Volume_MA']
        hist['Price_MA'] = hist['Close'].rolling(ma_window, min_periods=3).mean()
        hist['MA_Slope'] = hist['Price_MA'].pct_change(5)  # 5-day slope of MA
        hist['Price_Change'] = ((hist['Close'] - hist['Price_MA']) / hist['Price_MA']) * 100
        
        # Volatility (for detecting "quiet accumulation")
        hist['Daily_Range'] = (hist['High'] - hist['Low']) / hist['Close'] * 100
        hist['Avg_Range'] = hist['Daily_Range'].rolling(ma_window, min_periods=3).mean()
        
        # Up-close detection (close near high = bullish)
        hist['Close_Position'] = (hist['Close'] - hist['Low']) / (hist['High'] - hist['Low'] + 0.0001)
        
        # Fill NaN with sensible defaults instead of dropping
        hist['Volume_Ratio'] = hist['Volume_Ratio'].fillna(1.0)
        hist['MA_Slope'] = hist['MA_Slope'].fillna(0)
        hist['Returns'] = hist['Returns'].fillna(0)
        hist['Avg_Range'] = hist['Avg_Range'].fillna(hist['Daily_Range'])
        
        # Recent data (last 20 days or available)
        recent_days = min(20, data_len - ma_window)
        recent = hist.tail(recent_days).copy()
        
        if len(recent) < 5:
            return {"error": "Insufficient data after calculation"}
        
        # Detect phases with 3-regime volume
        high_volume_days = len(recent[recent['Volume_Ratio'] > 1.2])
        low_volume_days = len(recent[recent['Volume_Ratio'] < 0.8])
        neutral_volume_days = len(recent) - high_volume_days - low_volume_days
        
        # Price trend (with division by zero guard)
        first_price = recent['Close'].iloc[0]
        if first_price > 0:
            price_trend = (recent['Close'].iloc[-1] - first_price) / first_price * 100
        else:
            price_trend = 0.0
        
        # Volume trend (with division by zero guard)
        vol_head_mean = recent['Volume'].head(5).mean()
        vol_tail_mean = recent['Volume'].tail(5).mean()
        if vol_head_mean > 0:
            volume_trend = (vol_tail_mean - vol_head_mean) / vol_head_mean * 100
        else:
            volume_trend = 0.0
        
        # MA trend (for markdown confirmation)
        ma_slope = recent['MA_Slope'].iloc[-1] * 100 if not pd.isna(recent['MA_Slope'].iloc[-1]) else 0
        current_vs_ma = recent['Close'].iloc[-1] > recent['Price_MA'].iloc[-1]
        
        # Initialize scores with weights
        accumulation_score = 0.0
        distribution_score = 0.0
        markup_score = 0.0
        markdown_score = 0.0
        
        # Track consecutive down days for markdown confirmation
        consecutive_down = 0
        
        for i, (_, row) in enumerate(recent.iterrows()):
            returns_pct = row['Returns'] * 100 if not pd.isna(row['Returns']) else 0
            vol_ratio = row['Volume_Ratio'] if not pd.isna(row['Volume_Ratio']) else 1.0
            close_position = row['Close_Position'] if not pd.isna(row['Close_Position']) else 0.5
            daily_range = row['Daily_Range'] if not pd.isna(row['Daily_Range']) else 2.0
            avg_range = row['Avg_Range'] if not pd.isna(row['Avg_Range']) else 2.0
            price_vs_ma = row['Close'] > row['Price_MA'] if not pd.isna(row['Price_MA']) else True
            
            # Determine volume regime
            if vol_ratio > 1.2:
                vol_regime = 'HIGH'
                weight = 1.0
            elif vol_ratio < 0.8:
                vol_regime = 'LOW'
                weight = 0.5
            else:
                vol_regime = 'NEUTRAL'
                weight = 0.35  # Neutral volume still contributes but less
            
            # === ACCUMULATION DETECTION ===
            # Classic: High volume + sideways price
            if vol_regime == 'HIGH' and -2 < returns_pct < 2:
                accumulation_score += 1.0
            # Quiet accumulation: Normal/neutral volume + small range + close near high
            elif vol_regime == 'NEUTRAL' and daily_range < avg_range and close_position > 0.6 and returns_pct > -1:
                accumulation_score += 0.5
            # Accumulation on slight dip with strong close
            elif vol_regime in ['HIGH', 'NEUTRAL'] and -3 < returns_pct < 0 and close_position > 0.7:
                accumulation_score += weight * 0.7
            
            # === MARKUP DETECTION ===
            # Classic: High volume + price up significantly
            if vol_regime == 'HIGH' and returns_pct > 2:
                markup_score += 1.0
            # Moderate markup on neutral volume
            elif vol_regime == 'NEUTRAL' and returns_pct > 1.5:
                markup_score += 0.4
            # Strong up-close even on lower volume
            elif returns_pct > 0.5 and close_position > 0.8:
                markup_score += weight * 0.5
            
            # === DISTRIBUTION DETECTION ===
            # Classic: High volume + price down but still above MA
            if vol_regime == 'HIGH' and returns_pct < -2 and price_vs_ma:
                distribution_score += 1.0
            # Distribution sign: High volume + close near low (selling pressure)
            elif vol_regime == 'HIGH' and close_position < 0.3:
                distribution_score += 0.7
            # Neutral volume but weak close while price still high
            elif vol_regime == 'NEUTRAL' and close_position < 0.3 and price_vs_ma:
                distribution_score += 0.3
            
            # === MARKDOWN DETECTION (IMPROVED FOR IDX) ===
            # Di pasar Indonesia, markdown bisa terjadi dengan berbagai pola:
            # 1. Classic: Low volume + price drop (bandar pelan-pelan jual)
            # 2. Panic: High volume + price drop (distribusi massal)
            # 3. Grind down: Persistent small drops (death by thousand cuts)
            
            # Track consecutive down days
            if returns_pct < -0.5:
                consecutive_down += 1
            else:
                consecutive_down = 0
            
            # Pattern 1: Classic markdown - Low volume + significant drop + below MA
            if vol_regime == 'LOW' and returns_pct < -2 and not price_vs_ma:
                markdown_score += 1.0
            
            # Pattern 2: Panic selling - HIGH volume + big drop (distribusi agresif)
            # Di IDX ini sering terjadi saat bandar mau cabut cepat
            elif vol_regime == 'HIGH' and returns_pct < -3 and not price_vs_ma:
                markdown_score += 1.2  # Higher score untuk panic
            
            # Pattern 3: Consecutive down days - Grinding down
            elif consecutive_down >= 2 and not price_vs_ma:
                markdown_score += 0.6
            elif consecutive_down >= 3:  # 3+ hari turun berturut
                markdown_score += 0.8
            
            # Pattern 4: Breakdown support with any volume
            # Jika MA slope negatif dan harga di bawah MA
            elif not price_vs_ma and ma_slope < -0.5 and returns_pct < -1:
                markdown_score += 0.5
            
            # Pattern 5: Close near low (weak close) - tanda seller dominan
            if close_position < 0.2 and returns_pct < 0:
                markdown_score += 0.3
        
        # Additional markdown confirmation: Overall trend is down + below MA
        if not current_vs_ma and price_trend < -5 and ma_slope < 0:
            markdown_score += 2.0  # Bonus for confirmed downtrend
        
        # Additional markup confirmation: Overall trend is up + above MA
        if current_vs_ma and price_trend > 5 and ma_slope > 0:
            markup_score += 1.5  # Bonus for confirmed uptrend
        
        # Round scores
        scores = {
            'ACCUMULATION': round(accumulation_score, 1),
            'MARKUP': round(markup_score, 1),
            'DISTRIBUTION': round(distribution_score, 1),
            'MARKDOWN': round(markdown_score, 1)
        }
        
        # Determine current phase with minimum margin requirement
        max_score = max(scores.values())
        total_score = sum(scores.values())
        
        # Find the winning phase
        winning_phase = max(scores, key=scores.get)
        second_best = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
        
        # Require minimum margin (>=2 points OR >25% of total) to declare a phase
        margin = max_score - second_best
        margin_pct = (margin / total_score * 100) if total_score > 0 else 0
        
        if max_score < 2 or (margin < 2 and margin_pct < 25):
            current_phase = 'TRANSITION'
            phase_signal = {
                'TRANSITION': '🟡 WAIT - Fase transisi, belum ada sinyal kuat'
            }
        else:
            current_phase = winning_phase
            phase_signal = {
                'ACCUMULATION': '🟢 BUY ZONE - Bandar lagi ngumpulin',
                'MARKUP': '🔥 MOMENTUM - Bandar lagi pump, ikuti trend',
                'DISTRIBUTION': '🔴 CAUTION - Bandar mulai distribusi',
                'MARKDOWN': '⚪ AVOID - Bandar udah cabut'
            }
        
        # Calculate bandar strength (accumulation + markup indicates active bandar)
        bandar_strength = (scores['ACCUMULATION'] + scores['MARKUP']) / len(recent) * 100
        
        # Confidence based on margin and score
        if max_score >= 5 and margin >= 3:
            confidence = "HIGH"
        elif max_score >= 3 and margin >= 2:
            confidence = "MODERATE"
        else:
            confidence = "LOW"
        
        # ── Money Flow Indicators ──────────────────────────────────────────────
        obv_series  = _calc_obv(hist)
        cmf_series  = _calc_cmf(hist)
        mfi_series  = _calc_mfi(hist)
        vwap_series = _calc_vwap(hist)

        current_price = hist['Close'].iloc[-1]

        # OBV trend: bandingkan rata-rata 5 bar terakhir vs 5 bar sebelumnya
        obv_recent = obv_series.iloc[-5:].mean()
        obv_prev   = obv_series.iloc[-10:-5].mean()
        obv_trend_pct = ((obv_recent - obv_prev) / (abs(obv_prev) + 1)) * 100

        cmf_now  = float(cmf_series.iloc[-1]) if not pd.isna(cmf_series.iloc[-1]) else 0.0
        mfi_now  = float(mfi_series.iloc[-1]) if not pd.isna(mfi_series.iloc[-1]) else 50.0
        vwap_now = float(vwap_series.iloc[-1]) if not pd.isna(vwap_series.iloc[-1]) else current_price
        vwap_dev_pct = ((current_price - vwap_now) / (vwap_now + 1e-9)) * 100

        mf_signal = _money_flow_signal(cmf_now, mfi_now, obv_trend_pct, vwap_dev_pct)

        # ── Phase History ──────────────────────────────────────────────────────
        phase_history = _build_phase_history(hist)

        # ── Relative vs Market ─────────────────────────────────────────────────
        ticker_jk = ticker if ticker.endswith(".JK") else ticker + ".JK"
        rel_market = _calc_relative_vs_market(ticker_jk, period)

        # ── Divergence Detection ───────────────────────────────────────────────
        divergence = _detect_divergence(hist, obv_series, cmf_series, mfi_series, window=10)

        # Divergence dapat override phase confidence
        # Bearish div saat MARKUP/ACCUMULATION → turunkan bandar_strength
        # Bullish div saat MARKDOWN/DISTRIBUTION → naikkan sedikit
        div_adjustment = 0
        if divergence["detected"]:
            high_sev = divergence["high_severity_count"]
            if divergence["bias"] == "BEARISH_DIV" and current_phase in ("MARKUP", "ACCUMULATION"):
                div_adjustment = -(high_sev * 8)
            elif divergence["bias"] == "BULLISH_DIV" and current_phase in ("MARKDOWN", "DISTRIBUTION"):
                div_adjustment = +(high_sev * 6)

        # ── ARA/ARB Detection ──────────────────────────────────────────────────
        # Detect ARA/ARB patterns (unique untuk IDX)
        ara_arb_analysis = detect_ara_arb_pattern(hist)
        current_limits = get_ara_arb_limit(current_price)

        # Adjust bandar strength if ARA pattern detected
        if ara_arb_analysis['ara_hits'] >= 2:
            bandar_strength = min(100, bandar_strength * 1.3)

        # Blend money flow score + divergence adjustment into bandar_strength
        mf_boost = mf_signal['raw_score'] * 1.5  # -12..+12 contribution
        bandar_strength = max(0, min(100, bandar_strength + mf_boost + div_adjustment))

        return {
            "ticker": ticker.replace('.JK', ''),
            "analysis_period": period,
            "current_phase": {
                "phase": current_phase,
                "signal": phase_signal.get(current_phase, phase_signal.get('TRANSITION')),
                "strength": max_score,
                "confidence": confidence,
                "margin_vs_second": round(margin, 1)
            },
            "phase_scores": {
                "accumulation": scores['ACCUMULATION'],
                "markup": scores['MARKUP'],
                "distribution": scores['DISTRIBUTION'],
                "markdown": scores['MARKDOWN']
            },
            "phase_history": phase_history,
            "divergence": divergence,
            "relative_vs_market": rel_market,
            "money_flow_indicators": {
                "composite": mf_signal,
                "obv_trend_pct": round(obv_trend_pct, 2),
                "obv_direction": "RISING" if obv_trend_pct > 2 else "FALLING" if obv_trend_pct < -2 else "FLAT",
                "cmf": round(cmf_now, 4),
                "cmf_signal": "BUY" if cmf_now > 0.05 else "SELL" if cmf_now < -0.05 else "NEUTRAL",
                "mfi": round(mfi_now, 1),
                "mfi_zone": "OVERBOUGHT" if mfi_now > 80 else "OVERSOLD" if mfi_now < 20 else "BULLISH" if mfi_now > 60 else "BEARISH" if mfi_now < 40 else "NEUTRAL",
                "vwap": round(vwap_now, 2),
                "vwap_deviation_pct": round(vwap_dev_pct, 2),
                "vwap_position": "ABOVE" if vwap_dev_pct > 0 else "BELOW",
                "note": "Proxy indicators — bukan real broker flow IDX"
            },
            "price_action": {
                "trend_pct": round(price_trend, 2),
                "trend_direction": "UP" if price_trend > 5 else "DOWN" if price_trend < -5 else "SIDEWAYS",
                "current_price": round(current_price, 2),
                "ma": round(hist['Price_MA'].iloc[-1], 2),
                "ma_window": ma_window,
                "ma_slope": round(ma_slope, 2),
                "position_vs_ma": "ABOVE" if current_vs_ma else "BELOW"
            },
            "volume_action": {
                "high_volume_days": high_volume_days,
                "neutral_volume_days": neutral_volume_days,
                "low_volume_days": low_volume_days,
                "volume_trend_pct": round(volume_trend, 2),
                "volume_status": "INCREASING" if volume_trend > 20 else "DECREASING" if volume_trend < -20 else "STABLE"
            },
            "bandar_strength": {
                "score": round(bandar_strength, 2),
                "rating": "STRONG" if bandar_strength > 40 else "MODERATE" if bandar_strength > 20 else "WEAK",
                "active": bandar_strength > 25 or scores['MARKUP'] > 3 or scores['ACCUMULATION'] > 3
            },
            "ara_arb_analysis": {
                "ara_hits": ara_arb_analysis['ara_hits'],
                "arb_hits": ara_arb_analysis['arb_hits'],
                "near_ara": ara_arb_analysis['near_ara'],
                "near_arb": ara_arb_analysis['near_arb'],
                "pattern": ara_arb_analysis['pattern'],
                "is_volatile": ara_arb_analysis['is_volatile'],
                "board_type": current_limits['board_type'],
                "current_ara_limit": current_limits['ara_price'],
                "current_arb_limit": current_limits['arb_price'],
                "ara_pct": current_limits['ara_percentage'],
                "arb_pct": current_limits['arb_percentage'],
                "tick_size": current_limits['tick_size_ara'],
                "floor_price": current_limits['floor_price']
            },
            "recommendation": {
                "action": "BUY" if current_phase == 'ACCUMULATION' else "HOLD/RIDE" if current_phase == 'MARKUP' else "SELL" if current_phase == 'DISTRIBUTION' else "WAIT" if current_phase == 'TRANSITION' else "AVOID",
                "reason": phase_signal.get(current_phase, '🟡 WAIT - Fase transisi'),
                "risk_level": "LOW" if current_phase == 'ACCUMULATION' else "MODERATE" if current_phase in ['MARKUP', 'TRANSITION'] else "HIGH"
            }
        }
        
    except Exception as e:
        return {"error": str(e)}


def analyze_tape_reading(ticker: str, period: str = "5d") -> dict:
    """
    Analisis tape reading - membaca order flow dari price & volume action.
    
    Konsep:
    - Buying pressure: Price naik, volume tinggi, spread mengecil
    - Selling pressure: Price turun, volume tinggi, spread melebar
    - Absorption: Volume tinggi tapi price flat (ada yang nyerap)
    
    Args:
        ticker: Stock ticker
        period: Analysis period (5d untuk intraday reading)
        
    Returns:
        Dictionary dengan analisis tape reading
    """
    ticker = validate_ticker(ticker)
    
    try:
        hist_data = yahoo_api.get_historical_data(ticker, period=period, interval='1h')
        
        if 'error' in hist_data or 'data' not in hist_data:
            return {"error": "Insufficient intraday data"}
        
        # Convert to DataFrame
        hist = pd.DataFrame(hist_data['data'])
        
        if hist.empty or len(hist) < 10:
            return {"error": "Insufficient intraday data"}
        
        # Ensure proper column names
        hist.columns = [col.capitalize() for col in hist.columns]
        
        # Calculate metrics
        hist['Spread'] = ((hist['High'] - hist['Low']) / hist['Close']) * 100
        hist['Body'] = abs(hist['Close'] - hist['Open'])
        hist['Upper_Wick'] = hist['High'] - hist[['Close', 'Open']].max(axis=1)
        hist['Lower_Wick'] = hist[['Close', 'Open']].min(axis=1) - hist['Low']
        hist['Volume_MA'] = hist['Volume'].rolling(10).mean()
        hist['Volume_Ratio'] = hist['Volume'] / hist['Volume_MA']
        
        # Recent bars (last 10)
        recent = hist.tail(10)
        
        # Detect buying/selling pressure
        buying_bars = 0
        selling_bars = 0
        absorption_bars = 0
        
        for _, bar in recent.iterrows():
            price_change = ((bar['Close'] - bar['Open']) / bar['Open']) * 100
            
            if bar['Volume_Ratio'] > 1.2:  # High volume
                if price_change > 0.5:  # Price up
                    buying_bars += 1
                elif price_change < -0.5:  # Price down
                    selling_bars += 1
                elif abs(price_change) < 0.3:  # Price flat
                    absorption_bars += 1
        
        # Current market pressure
        if buying_bars > selling_bars * 1.5:
            pressure = "🟢 STRONG BUYING"
        elif buying_bars > selling_bars:
            pressure = "🟢 Buying"
        elif selling_bars > buying_bars * 1.5:
            pressure = "🔴 STRONG SELLING"
        elif selling_bars > buying_bars:
            pressure = "🔴 Selling"
        else:
            pressure = "⚪ Neutral"
        
        # Last bar analysis
        last_bar = recent.iloc[-1]
        last_price_change = ((last_bar['Close'] - last_bar['Open']) / last_bar['Open']) * 100
        
        # Order flow
        if last_bar['Volume_Ratio'] > 1.3 and last_price_change > 0:
            order_flow = "🔥 Aggressive Buying"
        elif last_bar['Volume_Ratio'] > 1.3 and last_price_change < 0:
            order_flow = "🔴 Aggressive Selling"
        elif absorption_bars >= 3:
            order_flow = "🟡 Absorption (Kuat Tahan)"
        else:
            order_flow = "⚪ Normal Flow"
        
        return {
            "ticker": ticker.replace('.JK', ''),
            "analysis_period": period,
            "current_pressure": {
                "pressure": pressure,
                "buying_bars": buying_bars,
                "selling_bars": selling_bars,
                "absorption_bars": absorption_bars
            },
            "order_flow": {
                "flow_type": order_flow,
                "last_bar_volume_ratio": round(last_bar['Volume_Ratio'], 2),
                "last_bar_change_pct": round(last_price_change, 2)
            },
            "last_bar_details": {
                "open": round(last_bar['Open'], 2),
                "high": round(last_bar['High'], 2),
                "low": round(last_bar['Low'], 2),
                "close": round(last_bar['Close'], 2),
                "volume": int(last_bar['Volume']),
                "spread_pct": round(last_bar['Spread'], 2),
                "body_size": round(last_bar['Body'], 2),
                "upper_wick": round(last_bar['Upper_Wick'], 2),
                "lower_wick": round(last_bar['Lower_Wick'], 2)
            },
            "interpretation": {
                "dominant_force": "BUYERS" if buying_bars > selling_bars else "SELLERS" if selling_bars > buying_bars else "BALANCED",
                "market_sentiment": "BULLISH" if buying_bars > selling_bars * 1.2 else "BEARISH" if selling_bars > buying_bars * 1.2 else "NEUTRAL",
                "immediate_action": "BUY" if pressure in ["🟢 STRONG BUYING", "🟢 Buying"] else "SELL" if "SELLING" in pressure else "WAIT"
            }
        }
        
    except Exception as e:
        return {"error": str(e)}



# ── Multi-Timeframe Confluence ─────────────────────────────────────────────────

_PHASE_SCORE = {
    "ACCUMULATION": +2,
    "MARKUP":       +1,
    "TRANSITION":    0,
    "DISTRIBUTION": -1,
    "MARKDOWN":     -2,
}

_TF_WEIGHTS = {
    "1mo": 1,
    "3mo": 2,
    "6mo": 3,
}


def analyze_bandarmology_mtf(ticker: str) -> dict:
    """
    Multi-timeframe bandarmology confluence.

    Jalankan analisis untuk 3 timeframe (1mo, 3mo, 6mo) lalu gabungkan:
    - Timeframe lebih panjang = bobot lebih besar
    - Fase scoring: ACCUMULATION=+2, MARKUP=+1, TRANSITION=0,
                    DISTRIBUTION=-1, MARKDOWN=-2
    - Weighted score → overall bias + actionable signal

    Contoh interpretasi:
      6mo=ACCUMULATION, 3mo=MARKUP, 1mo=MARKUP  → sangat bullish (semua align)
      6mo=MARKUP, 3mo=DISTRIBUTION, 1mo=MARKDOWN → topping, waspada
      6mo=MARKDOWN, 3mo=TRANSITION, 1mo=ACCUMULATION → early reversal, wait confirm
    """
    timeframes = ["1mo", "3mo", "6mo"]
    results = {}

    for tf in timeframes:
        r = analyze_bandarmology(ticker, tf)
        if "error" in r:
            results[tf] = {"error": r["error"]}
        else:
            results[tf] = {
                "phase":          r["current_phase"]["phase"],
                "confidence":     r["current_phase"]["confidence"],
                "strength":       r["current_phase"]["strength"],
                "bandar_strength": r["bandar_strength"]["score"],
                "mf_score":       r["money_flow_indicators"]["composite"]["score"],
                "divergence":     r["divergence"]["bias"],
                "div_summary":    r["divergence"]["summary"],
                "price_trend":    r["price_action"]["trend_pct"],
                "volume_status":  r["volume_action"]["volume_status"],
            }

    # ── Weighted confluence score ──────────────────────────────────────────
    total_weight = 0
    weighted_sum = 0.0
    phase_votes  = {}

    for tf, data in results.items():
        if "error" in data:
            continue
        w     = _TF_WEIGHTS[tf]
        score = _PHASE_SCORE.get(data["phase"], 0)
        weighted_sum += score * w
        total_weight += w
        phase_votes[tf] = data["phase"]

    if total_weight == 0:
        return {"ticker": ticker, "error": "Semua timeframe gagal diambil datanya"}

    confluence_score = round(weighted_sum / total_weight, 2)  # -2 .. +2

    # Normalize ke -100..+100
    normalized = round(confluence_score / 2 * 100, 1)

    # Overall bias
    if confluence_score >= 1.5:
        overall_bias   = "STRONG BULLISH"
        bias_signal    = "🔥 Semua TF align bullish — momentum kuat, bisa entry"
        action         = "BUY"
    elif confluence_score >= 0.5:
        overall_bias   = "BULLISH"
        bias_signal    = "🟢 Mayoritas TF bullish — perhatikan TF pendek untuk timing"
        action         = "BUY/WATCH"
    elif confluence_score >= -0.4:
        overall_bias   = "NEUTRAL"
        bias_signal    = "🟡 TF tidak align — tunggu konfirmasi lebih lanjut"
        action         = "WAIT"
    elif confluence_score >= -1.4:
        overall_bias   = "BEARISH"
        bias_signal    = "🟠 Mayoritas TF bearish — hindari entry baru"
        action         = "AVOID"
    else:
        overall_bias   = "STRONG BEARISH"
        bias_signal    = "🔴 Semua TF align bearish — AVOID atau pertimbangkan exit"
        action         = "AVOID/EXIT"

    # Alignment check
    unique_phases = set(phase_votes.values())
    if len(unique_phases) == 1:
        alignment = "PERFECT"
        alignment_note = f"Semua TF sepakat: {list(unique_phases)[0]}"
    elif len(unique_phases) == 2:
        alignment = "GOOD"
        alignment_note = f"2 dari 3 TF align"
    else:
        alignment = "MIXED"
        alignment_note = "Setiap TF beda fase — sinyal konflik"

    # Divergence across timeframes
    div_flags = [data.get("divergence", "CONFIRMED") for data in results.values() if "error" not in data]
    bullish_divs = sum(1 for d in div_flags if d == "BULLISH_DIV")
    bearish_divs = sum(1 for d in div_flags if d == "BEARISH_DIV")

    return {
        "ticker": ticker,
        "confluence": {
            "score": normalized,
            "raw_score": confluence_score,
            "overall_bias": overall_bias,
            "signal": bias_signal,
            "action": action,
            "alignment": alignment,
            "alignment_note": alignment_note,
        },
        "divergence_across_tf": {
            "bullish_div_count": bullish_divs,
            "bearish_div_count": bearish_divs,
            "note": (
                "⚠️ Bearish divergence di beberapa TF — waspada" if bearish_divs >= 2
                else "💡 Bullish divergence di beberapa TF — potensi reversal" if bullish_divs >= 2
                else "Normal"
            ),
        },
        "timeframes": results,
    }


# ==================== MCP TOOL WRAPPERS ====================

def get_foreign_flow_tool() -> Tool:
    """Get tool definition for foreign flow analysis."""
    return Tool(
        name="get_foreign_flow",
        description="Analisis Smart Money Proxy berdasarkan volume-price action. NOTE: Ini BUKAN real foreign net buy/sell dari BEI, tapi proxy berdasarkan pattern akumulasi/distribusi.",
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker saham IDX (contoh: BBRI, BBCA, TLKM)"
                },
                "period": {
                    "type": "string",
                    "description": "Periode analisis (default: 1mo). Pilihan: 7d, 1mo, 3mo, 6mo",
                    "default": "1mo"
                }
            },
            "required": ["ticker"]
        }
    )


async def get_foreign_flow(arguments: dict) -> dict:
    """Handle foreign flow analysis request."""
    ticker = arguments.get("ticker")
    period = arguments.get("period", "1mo")
    
    result = analyze_foreign_flow(ticker, period)
    return result


def get_bandarmology_tool() -> Tool:
    """Get tool definition for bandarmology analysis."""
    return Tool(
        name="get_bandarmology",
        description="Analisis bandarmology - deteksi fase akumulasi/markup/distribusi/markdown berdasarkan price-volume action.",
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker saham IDX (contoh: BBRI, BBCA, TLKM)"
                },
                "period": {
                    "type": "string",
                    "description": "Periode analisis (default: 3mo). Pilihan: 1mo, 3mo, 6mo, 1y",
                    "default": "3mo"
                }
            },
            "required": ["ticker"]
        }
    )


async def get_bandarmology(arguments: dict) -> dict:
    """Handle bandarmology analysis request."""
    ticker = arguments.get("ticker")
    period = arguments.get("period", "3mo")

    result = analyze_bandarmology(ticker, period)
    return result


def get_bandarmology_mtf_tool() -> Tool:
    return Tool(
        name="get_bandarmology_mtf",
        description=(
            "Multi-timeframe bandarmology confluence — analisis 1mo + 3mo + 6mo sekaligus "
            "untuk mendapat sinyal yang lebih kuat. Timeframe panjang diberi bobot lebih besar. "
            "Berguna untuk: 'apakah BBCA layak masuk sekarang?', 'konfirmasi phase di semua TF', "
            "'cari saham yang semua TF align bullish'"
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


async def get_bandarmology_mtf(arguments: dict) -> dict:
    return analyze_bandarmology_mtf(ticker=arguments.get("ticker", ""))


def get_tape_reading_tool() -> Tool:
    """Get tool definition for tape reading analysis."""
    return Tool(
        name="get_tape_reading",
        description="Analisis tape reading - membaca order flow dan pressure dari price & volume action intraday.",
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker saham IDX (contoh: BBRI, BBCA, TLKM)"
                },
                "period": {
                    "type": "string",
                    "description": "Periode analisis (default: 5d untuk intraday). Pilihan: 1d, 5d, 1mo",
                    "default": "5d"
                }
            },
            "required": ["ticker"]
        }
    )


async def get_tape_reading(arguments: dict) -> dict:
    """Handle tape reading analysis request."""
    ticker = arguments.get("ticker")
    period = arguments.get("period", "5d")
    
    result = analyze_tape_reading(ticker, period)
    return result

