import datetime
import pandas as pd
from yahooquery import Ticker

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
    # Define the date range using datetime objects.
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=30)
    
    # Create a single Ticker instance for all tickers.
    ticker_obj = Ticker(tickers)
    
    # Fetch historical data with a 1-day interval.
    history = ticker_obj.history(
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        interval="1d"
    )
    
    # Optional: Check which tickers are available in the returned MultiIndex.
    if hasattr(history.index, 'levels') and len(history.index.levels) > 0:
        available_tickers = list(history.index.levels[0])
        print("Available tickers in history:", available_tickers)
    else:
        available_tickers = tickers

    # Get the current price information (dictionary with ticker data)
    current_prices = ticker_obj.price

    result = {}
    
    # Process each ticker.
    for t in tickers:
        try:
            # Initialize with an empty list.
            prices = []
            if t not in history.index.levels[0]:
                print(f"Ticker {t} not found in history index. Available tickers: {list(history.index.levels[0])}")
            else:
                # Extract rows for this ticker.
                df = history.xs(t, level=0)
                
                # Remove timezone information: convert each timestamp to a formatted string and parse back.
                df.index = pd.to_datetime(df.index.map(lambda x: x.strftime("%Y-%m-%d %H:%M:%S")))
                df = df.sort_index()
                
                # Extract the close prices as a list.
                prices = df['close'].tolist()
            
            # Get the current price for ticker 't', for example from the "regularMarketPrice" field.
            # If not available, current_price will be None.
            current_price = current_prices.get(t, {}).get("regularMarketPrice", None)
            # Append the current price to the historical close price list.
            prices.append(current_price)
            
            result[t] = prices
        except Exception as e:
            print(f"Error processing ticker {t}: {e}")
            result[t] = []
    
    return result

