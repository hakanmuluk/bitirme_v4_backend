# routes/logout_route.py

from fastapi import APIRouter, Request
from controllers.authController import logout_user_api

router = APIRouter()

@router.post("/logout", tags=["auth"])
async def logout(request: Request):
    """
    API endpoint to log out the current user.
    Calls the controller function to clear cookies and session.
    """
    return await logout_user_api(request)
