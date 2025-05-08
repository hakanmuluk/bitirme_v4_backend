# services/stockService.py

import datetime
import time
from dateutil.relativedelta import relativedelta
import yfinance as yf
import constants

def format_market_cap(num):
    """
    Formats a raw market capitalization number into a human-readable string.
    """
    if num is None:
        return None
    if num >= 1e9:
        return f"{num / 1e9:.2f}B"
    if num >= 1e6:
        return f"{num / 1e6:.2f}M"
    return str(num)

def fetch_stock_data(symbols, pause=1.0, max_retries=3):
    """
    Fetches for each BIST symbol using yfinance:
      - Current price
      - Daily % change
      - 1‑month % change (based on a 30‑day calendar window)
      - Year‑to‑date % change
      - Market cap

    Includes a pause between symbols and simple retry on rate‑limit (429) errors.
    """
    results = []
    now = datetime.datetime.utcnow()
    one_month_ago = now - relativedelta(months=1)
    start_of_year = datetime.datetime(now.year, 1, 1)

    for sym in symbols:
        yf_sym = f"{sym}.IS"
        attempts = 0

        while attempts < max_retries:
            try:
                # Throttle between requests
                time.sleep(pause)

                # Initialize the Ticker
                ticker = yf.Ticker(yf_sym)

                # Fetch full-year daily history
                hist = ticker.history(
                    start=start_of_year.strftime("%Y-%m-%d"),
                    end=(now + datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
                    interval="1d"
                )
                if hist.empty or len(hist) < 2:
                    raise Exception("Not enough historical data")

                # Compute latest and previous close
                latest_close = hist["Close"].iloc[-1]
                prev_close   = hist["Close"].iloc[-2]
                day_change   = (latest_close - prev_close) / prev_close * 100 if prev_close else None

                # Compute 1‑month change via a calendar window
                hist_1mo = ticker.history(
                    start=one_month_ago.strftime("%Y-%m-%d"),
                    end=(now + datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
                    interval="1d"
                )
                month_pct = None
                if not hist_1mo.empty:
                    first = hist_1mo["Close"].iloc[0]
                    month_pct = (latest_close - first) / first * 100 if first else None

                # Compute YTD change
                first_ytd = hist["Close"].iloc[0]
                ytd_pct   = (latest_close - first_ytd) / first_ytd * 100 if first_ytd else None

                # Fetch market cap from ticker.info
                info = ticker.info or {}
                market_cap = info.get("marketCap")

                company_name = constants.bist100["Borsa İstanbul"]["processed_industries_sector"].get(sym, sym)

                results.append({
                    "ticker": sym,
                    "company": company_name,
                    "price": latest_close,
                    "dayChange": day_change,
                    "monthChange": month_pct,
                    "ytdChange": ytd_pct,
                    "marketCap": format_market_cap(market_cap)
                })
                break  # success, exit retry loop

            except Exception as e:
                err = str(e)
                # On rate-limit, back off exponentially
                if "429" in err or "Too Many Requests" in err:
                    attempts += 1
                    backoff = pause * (2 ** attempts)
                    time.sleep(backoff)
                else:
                    # Non-retryable error: record it and stop retries
                    results.append({"ticker": sym, "error": err})
                    break
        else:
            # Exhausted retries
            results.append({"ticker": sym, "error": f"failed after {max_retries} attempts"})

    # Sort by price descending
    results.sort(key=lambda x: x.get("price", 0) or 0, reverse=True)
    return results