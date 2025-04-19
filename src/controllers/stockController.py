# stock_controller.py

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool
from services.stockService import fetch_stock_data
import constants

router = APIRouter()

@router.get("/stock-data")
async def get_stock_data():
    """
    Endpoint to fetch BIST 100 stock data.
    
    It extracts all symbols from the "Borsa İstanbul" section of the constants,
    calls the stock service to fetch their data, and returns the result as JSON.
    """
    try:
        # Flatten all symbols from each sector under "Borsa İstanbul"
        sectors = constants.bist100.get("Borsa İstanbul", {})
        symbols = [symbol for sector in sectors.values() for symbol in sector.keys()]
        
        # Since stockService.fetch_stock_data is synchronous, execute it in a threadpool.
        stock_data = await run_in_threadpool(fetch_stock_data, symbols)
        return stock_data
    except Exception as error:
        print("Error fetching BIST 100 stock data:", error)
        raise HTTPException(status_code=500, detail="Failed to fetch BIST 100 stock data")
