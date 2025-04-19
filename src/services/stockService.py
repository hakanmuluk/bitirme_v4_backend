# services/stockService.py

import datetime
from yahooquery import Ticker

def normalize_price(quote):
    """
    Adjusts the price if the stock data is in TRY (Turkish Lira) and the price is unusually high,
    indicating it may be in kuruş (1/1000 of a lira).
    """
    price = quote.get('regularMarketPrice', 0)
    if quote.get('currency') == "TRY" and price > 1000:
        return price / 1000
    return price

def format_market_cap(num):
    """
    Returns a formatted string for the market cap number.
    """
    if num >= 1e9:
        return f"{num / 1e9:.2f}B"
    if num >= 1e6:
        return f"{num / 1e6:.2f}M"
    return str(num)

def fetch_stock_data(symbols):
    """
    Fetches stock data for each symbol from Yahoo Finance using yahooquery.
    
    It retrieves:
      - Quote data (company name, price, day change, market cap)
      - One-month historical data and year-to-date (YTD) historical data to compute percentage changes.
    
    All data is fetched in a few API calls instead of sequential requests.
    
    Returns a sorted list (by descending price) of stock data dictionaries.
    """
    # Create a Ticker instance for all symbols
    ticker = Ticker(symbols)
    
    # Fetch quote data for all symbols at once.
    # prices is a dict keyed by each symbol.
    prices = ticker.price

    now = datetime.datetime.now()
    start_of_year = datetime.datetime(now.year, 1, 1)

    # Fetch historical data in bulk.
    # The 'period' and 'start' arguments help get the 1-month and YTD data, respectively.
    hist_1mo = ticker.history(period='1mo', interval='1d')
    hist_ytd = ticker.history(start=start_of_year, interval='1d')

    # Group the DataFrames by symbol if data was successfully returned.
    grouped_1mo = {}
    if not hist_1mo.empty:
        for symbol, group in hist_1mo.groupby(level=0):
            grouped_1mo[symbol] = group
    grouped_ytd = {}
    if not hist_ytd.empty:
        for symbol, group in hist_ytd.groupby(level=0):
            grouped_ytd[symbol] = group

    def calc_change(df):
        """
        Calculates the percentage change between the first and last valid closing prices in the DataFrame.
        Expects df to have a 'close' column.
        """
        if df is not None and not df.empty:
            first = df['close'].iloc[0]
            last = df['close'].iloc[-1]
            if first:
                return (last - first) / first
        return 0

    results = []
    for symbol in symbols:
        try:
            quote = prices.get(symbol, {})
            hist_data_1mo = grouped_1mo.get(symbol)
            hist_data_ytd = grouped_ytd.get(symbol)

            stock_data = {
                "ticker": quote.get('symbol', symbol),
                "company": quote.get('longName') or symbol,
                "price": normalize_price(quote),
                "dayChange": quote.get('regularMarketChangePercent'),
                "monthChange": calc_change(hist_data_1mo),
                "yearChange": calc_change(hist_data_ytd),
                "marketCap": format_market_cap(quote.get('marketCap')) if quote.get('marketCap') is not None else None
            }
            results.append(stock_data)
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            results.append(None)

    # Filter out any failed fetches and sort the results by price in descending order.
    results = [r for r in results if r is not None]
    results.sort(key=lambda x: x.get('price', 0), reverse=True)
    return results


