from fastapi import APIRouter, Request, Form
from controllers.favoriteController import (
    add_favorite_company_api,
    remove_favorite_company_api,
    get_favorite_companies_api
)

router = APIRouter()

@router.post("/add")
async def add_favorite(request: Request, company: str = Form(...)):
    """
    Add a company to the authenticated user's favoriteCompanies array.
    Expects 'session' cookie and form field 'company'.
    """
    return await add_favorite_company_api(request, company)


@router.post("/remove")
async def remove_favorite(request: Request, company: str = Form(...)):
    """
    Remove a company from the authenticated user's favoriteCompanies array.
    Expects 'session' cookie and form field 'company'.
    """
    return await remove_favorite_company_api(request, company)

@router.get("/get")
async def list_favorites(request: Request):
    """
    Get the authenticated user's favoriteCompanies array.
    Expects 'session' cookie.
    """
    return await get_favorite_companies_api(request)