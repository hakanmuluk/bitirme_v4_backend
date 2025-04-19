# routes/logout_route.py

from fastapi import APIRouter, Request, Response
from controllers.authController import logout_user_api

router = APIRouter()

@router.get("/logout")
async def logout(request: Request, response: Response):
    """
    API endpoint to log out the current user.
    It calls the controller function to clear the session and returns a redirect response.
    """
    return await logout_user_api(request, response)
