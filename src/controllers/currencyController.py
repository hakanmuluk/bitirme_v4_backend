from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool
import constants
from services.currencyService import fetch_currency_data

router = APIRouter()

@router.get("/currency-data")
async def get_currency_data():
    """
    Endpoint to fetch currency data.
    
    It extracts the tickers under the "BIST & Currencies" section of the constants,
    calls the currency service to fetch their historical closing prices (with the current price appended),
    and returns the result as JSON.
    """
    try:
        tickers = constants.bist100.get("BIST & Currencies", {}).get("tickers", [])
        # Execute the synchronous currency service in a threadpool.
        currency_data = await run_in_threadpool(fetch_currency_data, tickers)
        return currency_data
    except Exception as error:
        print("Error fetching currency data:", error)
        raise HTTPException(status_code=500, detail="Failed to fetch currency data")
    
    
    
    