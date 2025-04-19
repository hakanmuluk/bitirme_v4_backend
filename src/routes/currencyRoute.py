# routes/currency_route.py

from fastapi import APIRouter
from controllers.currencyController import get_currency_data

router = APIRouter()

@router.get("/")
async def currency_data():
    """
    Calls the currency controller to fetch and return currency data.
    """
    return await get_currency_data()
