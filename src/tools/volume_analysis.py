"""Tool for volume analysis."""

from typing import Any, Dict
import pandas as pd
import numpy as np
from mcp.types import Tool
from src.utils.yahoo import yahoo_client, YahooFinanceError
from src.utils.validators import validate_ticker
from src.utils.exceptions import InvalidParameterError, DataUnavailableError, NetworkError
from src.utils.cache import cache_manager


def calculate_v60(clean_ticker: str, current_volume: int) -> Dict[str, Any]:
    """Calculate V60 ratio using tradingview_screener."""
    try:
        from tradingview_screener import Query
        _, df_tv = (Query()
            .set_markets("indonesia")
            .select("average_volume_60d_calc")
            .set_tickers(f"IDX:{clean_ticker}")
            .get_scanner_data())

        if df_tv.empty:
            return {"error": "No data from screener"}

        avg_v60_raw = df_tv.iloc[0]["average_volume_60d_calc"]
        if avg_v60_raw is None or (isinstance(avg_v60_raw, float) and np.isnan(avg_v60_raw)):
            return {"error": "average_volume_60d_calc is null"}

        avg_v60 = int(avg_v60_raw)
        vol_ratio = round(current_volume / avg_v60, 2) if avg_v60 > 0 else 0.0

        if vol_ratio >= 2.5:
            signal = "KAMEHAMEHA"
        elif vol_ratio >= 1.5:
            signal = "HIGH"
        elif vol_ratio < 0.5:
            signal = "LOW"
        else:
            signal = "NORMAL"

        return {
            "avg_volume_60d": avg_v60,
            "vol_ratio_v60": vol_ratio,
            "signal": signal,
            "kamehameha": vol_ratio >= 2.5,
        }
    except Exception as e:
        return {"error": str(e)}


def calculate_obv_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """Calculate OBV trend and divergence analysis."""
    try:
        closes = df["close"].values
        volumes = df["volume"].values

        # Compute OBV manually (no pandas_ta dependency)
        obv = np.zeros(len(closes))
        obv[0] = volumes[0]
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                obv[i] = obv[i - 1] + volumes[i]
            elif closes[i] < closes[i - 1]:
                obv[i] = obv[i - 1] - volumes[i]
            else:
                obv[i] = obv[i - 1]

        current_obv = float(obv[-1])

        # OBV change over 5 and 20 bars
        def pct_change(series, lookback):
            if len(series) > lookback:
                base = series[-(lookback + 1)]
                if base != 0:
                    return round((series[-1] - base) / abs(base) * 100, 2)
            return 0.0

        obv_5d_change_pct = pct_change(obv, 5)
        obv_20d_change_pct = pct_change(obv, 20)

        if obv_20d_change_pct > 10:
            obv_trend = "STRONG_UP"
        elif obv_20d_change_pct > 3:
            obv_trend = "UP"
        elif obv_20d_change_pct < -10:
            obv_trend = "STRONG_DOWN"
        elif obv_20d_change_pct < -3:
            obv_trend = "DOWN"
        else:
            obv_trend = "FLAT"

        # Price 20d change direction
        price_20d_pct = pct_change(closes, 20)
        price_up = price_20d_pct > 1.0
        price_down = price_20d_pct < -1.0
        obv_up = obv_20d_change_pct > 3.0
        obv_down = obv_20d_change_pct < -3.0

        if price_down and obv_up:
            divergence = "BULLISH_DIV"
        elif price_up and obv_down:
            divergence = "BEARISH_DIV"
        else:
            divergence = "NONE"

        # Signal classification
        if obv_up and (price_down or abs(price_20d_pct) <= 1.0):
            signal = "ACCUMULATION"
        elif obv_down and price_up:
            signal = "DISTRIBUTION"
        elif obv_up and price_up:
            signal = "ALIGNED_UP"
        elif obv_down and price_down:
            signal = "ALIGNED_DOWN"
        else:
            signal = "NEUTRAL"

        return {
            "current_obv": current_obv,
            "obv_5d_change_pct": obv_5d_change_pct,
            "obv_20d_change_pct": obv_20d_change_pct,
            "obv_trend": obv_trend,
            "price_obv_divergence": divergence,
            "signal": signal,
        }
    except Exception as e:
        return {"error": str(e)}


def classify_vsa_bar(spread: float, volume: float, close_pos: float,
                     avg_spread: float, avg_volume: float) -> str:
    """Classify a single bar using VSA rules."""
    spread_ratio = spread / avg_spread if avg_spread > 0 else 1.0
    vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

    high_vol = vol_ratio >= 1.5
    very_high_vol = vol_ratio >= 2.5
    low_vol = vol_ratio < 0.7
    wide_spread = spread_ratio >= 1.3
    narrow_spread = spread_ratio < 0.7
    near_high = close_pos >= 0.7
    near_low = close_pos <= 0.3

    if very_high_vol and wide_spread and near_high:
        return "BUYING_CLIMAX"
    if very_high_vol and wide_spread and near_low:
        return "SELLING_CLIMAX"
    if very_high_vol and narrow_spread:
        return "STOPPING_VOLUME"
    if high_vol and wide_spread and near_high:
        return "EFFORT_TO_RISE"
    if high_vol and wide_spread and near_low:
        return "EFFORT_TO_FALL"
    if low_vol and narrow_spread and near_high:
        return "NO_DEMAND"
    if low_vol and narrow_spread and near_low:
        return "NO_SUPPLY"
    return "NEUTRAL"


def calculate_vsa(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute VSA for the last 5 bars."""
    try:
        if len(df) < 6:
            return {"error": "Insufficient data for VSA (need >=6 bars)"}

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        volumes = df["volume"].values
        dates = df.index

        spreads = highs - lows

        # Use last 20 bars as benchmark
        bench_end = len(spreads)
        bench_start = max(0, bench_end - 20)
        avg_spread = float(np.mean(spreads[bench_start:bench_end]))
        avg_volume = float(np.mean(volumes[bench_start:bench_end]))

        last_5_bars = []
        for i in range(-5, 0):
            spread = float(spreads[i])
            vol = float(volumes[i])
            h = float(highs[i])
            lo = float(lows[i])
            c = float(closes[i])
            close_pos = round((c - lo) / (h - lo), 3) if (h - lo) > 0 else 0.5

            pattern = classify_vsa_bar(spread, vol, close_pos, avg_spread, avg_volume)
            date_str = str(dates[i].date()) if hasattr(dates[i], "date") else str(dates[i])[:10]

            last_5_bars.append({
                "date": date_str,
                "close": round(c, 2),
                "spread_vs_avg": round(spread / avg_spread, 2) if avg_spread > 0 else 0.0,
                "volume_vs_avg": round(vol / avg_volume, 2) if avg_volume > 0 else 0.0,
                "close_position": close_pos,
                "pattern": pattern,
            })

        current_pattern = last_5_bars[-1]["pattern"]

        bullish_patterns = {"EFFORT_TO_RISE", "NO_SUPPLY", "BUYING_CLIMAX"}
        bearish_patterns = {"EFFORT_TO_FALL", "NO_DEMAND", "SELLING_CLIMAX"}

        if current_pattern in bullish_patterns:
            vsa_signal = "BULLISH"
        elif current_pattern in bearish_patterns:
            vsa_signal = "BEARISH"
        else:
            vsa_signal = "NEUTRAL"

        pattern_notes = {
            "BUYING_CLIMAX": "Very high volume + wide spread closing near high — possible exhaustion top",
            "SELLING_CLIMAX": "Very high volume + wide spread closing near low — possible bottom reversal",
            "STOPPING_VOLUME": "Very high volume + narrow spread — indecision, watch next bar",
            "EFFORT_TO_RISE": "High volume + wide spread closing near high — strong buying pressure",
            "EFFORT_TO_FALL": "High volume + wide spread closing near low — strong selling pressure",
            "NO_DEMAND": "Low volume + narrow spread closing near high — weak rally, bulls losing steam",
            "NO_SUPPLY": "Low volume + narrow spread closing near low — weak selloff, bears losing steam",
            "NEUTRAL": "No clear VSA pattern on current bar",
        }
        note = pattern_notes.get(current_pattern, "No clear VSA pattern")

        return {
            "last_5_bars": last_5_bars,
            "current_pattern": current_pattern,
            "vsa_signal": vsa_signal,
            "note": note,
        }
    except Exception as e:
        return {"error": str(e)}


def get_volume_analysis_tool() -> Tool:
    """Get volume analysis tool definition."""
    return Tool(
        name="get_volume_analysis",
        description="Menganalisis volume trading saham IDX. Menghitung average volume, volume spikes, volume trend, dan korelasi volume-harga.",
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker saham IDX (contoh: BBCA, BBRI, TLKM)",
                },
                "period": {
                    "type": "string",
                    "description": "Periode analisis (7d, 30d, 90d, 1mo, 3mo, 6mo, 1y)",
                    "default": "30d",
                },
            },
            "required": ["ticker"],
        },
    )


def calculate_volume_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate volume metrics from DataFrame.
    
    Args:
        df: DataFrame with date, volume, and price columns
        
    Returns:
        Dictionary with volume metrics
    """
    if df.empty or len(df) < 2:
        return {}
    
    volumes = df["volume"].values
    closes = df["close"].values
    
    # Current and recent volumes
    current_volume = int(volumes[-1]) if len(volumes) > 0 else 0
    previous_volume = int(volumes[-2]) if len(volumes) > 1 else 0
    
    # Average volumes for different periods
    avg_7d = int(np.mean(volumes[-7:])) if len(volumes) >= 7 else int(np.mean(volumes)) if len(volumes) > 0 else 0
    avg_30d = int(np.mean(volumes[-30:])) if len(volumes) >= 30 else int(np.mean(volumes)) if len(volumes) > 0 else 0
    avg_90d = int(np.mean(volumes[-90:])) if len(volumes) >= 90 else int(np.mean(volumes)) if len(volumes) > 0 else 0
    avg_all = int(np.mean(volumes)) if len(volumes) > 0 else 0
    
    # Volume ratios
    volume_ratio_7d = round((current_volume / avg_7d) if avg_7d > 0 else 0, 2)
    volume_ratio_30d = round((current_volume / avg_30d) if avg_30d > 0 else 0, 2)
    volume_ratio_90d = round((current_volume / avg_90d) if avg_90d > 0 else 0, 2)
    
    # Volume spike detection
    is_spike_7d = volume_ratio_7d >= 2.0
    is_spike_30d = volume_ratio_30d >= 2.0
    is_spike_90d = volume_ratio_90d >= 2.0
    
    spike_severity = "none"
    if is_spike_7d or is_spike_30d or is_spike_90d:
        max_ratio = max(volume_ratio_7d, volume_ratio_30d, volume_ratio_90d)
        if max_ratio >= 5.0:
            spike_severity = "extreme"
        elif max_ratio >= 3.0:
            spike_severity = "high"
        else:
            spike_severity = "moderate"
    
    # Volume trend analysis
    if len(volumes) >= 7:
        recent_7d_avg = np.mean(volumes[-7:])
        previous_7d_avg = np.mean(volumes[-14:-7]) if len(volumes) >= 14 else recent_7d_avg
        trend_7d = "increasing" if recent_7d_avg > previous_7d_avg * 1.1 else "decreasing" if recent_7d_avg < previous_7d_avg * 0.9 else "stable"
    else:
        trend_7d = "insufficient_data"
    
    if len(volumes) >= 30:
        recent_30d_avg = np.mean(volumes[-30:])
        previous_30d_avg = np.mean(volumes[-60:-30]) if len(volumes) >= 60 else recent_30d_avg
        trend_30d = "increasing" if recent_30d_avg > previous_30d_avg * 1.1 else "decreasing" if recent_30d_avg < previous_30d_avg * 0.9 else "stable"
    else:
        trend_30d = "insufficient_data"
    
    # Volume-price correlation
    volume_price_corr = 0.0
    if len(volumes) >= 10 and len(closes) >= 10:
        # Calculate price changes
        price_changes = np.diff(closes) / np.maximum(closes[:-1], 0.01)  # Avoid div by zero properly
        volume_changes = np.diff(volumes) / np.maximum(volumes[:-1], 1)  # Use max instead of adding 1
        
        # Calculate correlation
        if len(price_changes) > 1 and len(volume_changes) > 1:
            valid_indices = ~(np.isnan(price_changes) | np.isnan(volume_changes) | np.isinf(price_changes) | np.isinf(volume_changes))
            if np.sum(valid_indices) >= 5:
                price_changes_clean = price_changes[valid_indices]
                volume_changes_clean = volume_changes[valid_indices]
                if len(price_changes_clean) > 1 and len(volume_changes_clean) > 1:
                    corr_matrix = np.corrcoef(price_changes_clean, volume_changes_clean)
                    volume_price_corr = round(float(corr_matrix[0, 1]), 3) if not np.isnan(corr_matrix[0, 1]) else 0.0
    
    # Volume interpretation
    correlation_interpretation = (
        "strong_positive" if volume_price_corr >= 0.7
        else "moderate_positive" if volume_price_corr >= 0.3
        else "weak_positive" if volume_price_corr > 0
        else "weak_negative" if volume_price_corr >= -0.3
        else "moderate_negative" if volume_price_corr >= -0.7
        else "strong_negative" if volume_price_corr < -0.7
        else "no_correlation"
    )
    
    # Volume statistics
    max_volume = int(np.max(volumes)) if len(volumes) > 0 else 0
    min_volume = int(np.min(volumes)) if len(volumes) > 0 else 0
    volume_std = int(np.std(volumes)) if len(volumes) > 0 else 0
    
    # Unusual volume detection
    z_score = (current_volume - avg_all) / (volume_std + 1) if volume_std > 0 else 0
    is_unusual = abs(z_score) >= 2.0
    unusual_type = "high" if z_score >= 2.0 else "low" if z_score <= -2.0 else "normal"
    
    return {
        "current_volume": current_volume,
        "previous_volume": previous_volume,
        "volume_change": current_volume - previous_volume if previous_volume > 0 else 0,
        "volume_change_percent": round(((current_volume - previous_volume) / previous_volume * 100) if previous_volume > 0 else 0, 2),
        "averages": {
            "7d": avg_7d,
            "30d": avg_30d,
            "90d": avg_90d,
            "all_time": avg_all,
        },
        "volume_ratios": {
            "vs_7d_avg": volume_ratio_7d,
            "vs_30d_avg": volume_ratio_30d,
            "vs_90d_avg": volume_ratio_90d,
        },
        "spike_detection": {
            "is_spike_7d": is_spike_7d,
            "is_spike_30d": is_spike_30d,
            "is_spike_90d": is_spike_90d,
            "severity": spike_severity,
        },
        "trend": {
            "7d": trend_7d,
            "30d": trend_30d,
        },
        "volume_price_correlation": {
            "correlation": volume_price_corr,
            "interpretation": correlation_interpretation,
        },
        "statistics": {
            "max_volume": max_volume,
            "min_volume": min_volume,
            "std_deviation": volume_std,
        },
        "unusual_volume": {
            "is_unusual": is_unusual,
            "type": unusual_type,
            "z_score": round(z_score, 2),
        },
    }


async def get_volume_analysis(args: dict[str, Any]) -> dict[str, Any]:
    """
    Get comprehensive volume analysis.
    
    Args:
        args: Dictionary with 'ticker' and optional 'period' key
        
    Returns:
        Dictionary with volume analysis
    """
    try:
        ticker = validate_ticker(args.get("ticker", ""))
        period = args.get("period", "30d")
        
        # Validate period
        valid_periods = ["7d", "30d", "90d", "1mo", "3mo", "6mo", "1y"]
        if period not in valid_periods:
            period = "30d"
        
        # Check cache
        cache_key = cache_manager.generate_key("volume_analysis", ticker, period)
        cached = cache_manager.get("historical_daily", cache_key)  # Use historical_daily cache
        if cached:
            return cached
        
        # Get historical data
        hist_data = yahoo_client.get_historical_data(ticker, period=period, interval="1d")
        if "error" in hist_data:
            raise DataUnavailableError(f"Tidak dapat mengambil data historical untuk {ticker}")

        if not hist_data.get("data") or len(hist_data["data"]) < 2:
            raise DataUnavailableError(f"Data historical tidak cukup untuk analisis volume {ticker}")

        # Convert to DataFrame
        df_data = hist_data["data"]
        df = pd.DataFrame(df_data)
        df["Date"] = pd.to_datetime(df["date"])
        df.set_index("Date", inplace=True)

        # Ensure volume column exists and is numeric
        if "volume" not in df.columns:
            raise DataUnavailableError(f"Data volume tidak tersedia untuk {ticker}")

        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["high"] = pd.to_numeric(df.get("high", df["close"]), errors="coerce")
        df["low"] = pd.to_numeric(df.get("low", df["close"]), errors="coerce")

        # Remove rows with invalid data
        df = df[(df["volume"] >= 0) & (df["close"] > 0)]

        if df.empty or len(df) < 2:
            raise DataUnavailableError(f"Data tidak valid untuk analisis volume {ticker}")

        # Get current price
        price_data = yahoo_client.get_current_price(ticker)
        current_price = price_data.get("price", 0)

        # Calculate volume metrics
        volume_metrics = calculate_volume_metrics(df)
        current_volume = volume_metrics.get("current_volume", 0)

        # --- V60 ratio via tradingview_screener ---
        v60_data: Dict[str, Any] = {}
        try:
            v60_data = calculate_v60(ticker, current_volume)
        except Exception as _e:
            v60_data = {"error": str(_e)}

        # --- OBV trend analysis ---
        obv_data: Dict[str, Any] = {}
        try:
            obv_data = calculate_obv_analysis(df)
        except Exception as _e:
            obv_data = {"error": str(_e)}

        # --- VSA (Volume Spread Analysis) ---
        vsa_data: Dict[str, Any] = {}
        try:
            vsa_data = calculate_vsa(df)
        except Exception as _e:
            vsa_data = {"error": str(_e)}

        # Prepare result
        result = {
            "ticker": ticker,
            "name": price_data.get("name", ""),
            "current_price": round(current_price, 2),
            "period": period,
            "data_points": len(df),
            **volume_metrics,
            "v60": v60_data,
            "obv_analysis": obv_data,
            "vsa": vsa_data,
            "summary": {
                "current_volume_status": (
                    "spike" if volume_metrics.get("spike_detection", {}).get("severity") != "none"
                    else "above_average" if volume_metrics.get("volume_ratios", {}).get("vs_30d_avg", 0) > 1.2
                    else "below_average" if volume_metrics.get("volume_ratios", {}).get("vs_30d_avg", 0) < 0.8
                    else "normal"
                ),
                "trend": volume_metrics.get("trend", {}).get("30d", "unknown"),
                "correlation_strength": volume_metrics.get("volume_price_correlation", {}).get("interpretation", "unknown"),
                "v60_signal": v60_data.get("signal", "UNKNOWN"),
                "obv_trend": obv_data.get("obv_trend", "UNKNOWN"),
                "vsa_signal": vsa_data.get("vsa_signal", "NEUTRAL"),
            },
        }

        # Cache result (use historical_daily cache type)
        cache_manager.set("historical_daily", cache_key, result)
        
        return result
        
    except ValueError as e:
        raise InvalidParameterError(str(e))
    except YahooFinanceError as e:
        raise DataUnavailableError(str(e))
    except Exception as e:
        raise NetworkError(f"Gagal melakukan analisis volume: {str(e)}")


