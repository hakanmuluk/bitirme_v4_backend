import datetime
import pandas as pd
import yfinance as yf

def fetch_currency_data(tickers):
    """
    Fetches the closing prices for the last 7 days for each ticker in the provided list,
    and appends the current price to the end of each ticker's array.

    Args:
        tickers (list): List of ticker strings, e.g. ["USDTRY=X", "EURTRY=X"].

    Returns:
        dict: A dictionary where each key is a ticker symbol and the value is a list of closing prices,
              with the current price appended at the end.
    """
    result = {}

    for t in tickers:
        try:
            ticker = yf.Ticker(t)
            # Fetch last 7 days of history with 1-day interval
            hist = ticker.history(period="7d", interval="1d")
            # Extract closing prices as a list
            prices = hist['Close'].tolist()
            # Get current price from fast_info or fallback to last close
            current_price = None
            if hasattr(ticker, "fast_info") and "last_price" in ticker.fast_info:
                current_price = ticker.fast_info["last_price"]
            if current_price is None and len(prices) > 0:
                current_price = prices[-1]
            # Append current price to prices list
            prices.append(current_price)
            result[t] = prices
        except Exception as e:
            print(f"Error processing ticker {t}: {e}")
            result[t] = []

    return result
