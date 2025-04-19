# routes/login_route.py

from fastapi import APIRouter, Request, Response, Form
from controllers.authController import login_user_api

router = APIRouter()

@router.post("/login")
async def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
):
    return await login_user_api(request, response, email, password)
