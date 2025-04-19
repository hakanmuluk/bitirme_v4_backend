# routes/stock_route.py

from fastapi import APIRouter
from controllers.stockController import get_stock_data

router = APIRouter()

@router.get("/")
async def stock_data():
    """
    Calls the stock controller to fetch and return BIST 100 stock data.
    """
    return await get_stock_data()
