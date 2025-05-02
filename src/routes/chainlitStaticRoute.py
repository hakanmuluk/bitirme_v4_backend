# routes/chainlitStaticRoute.py
from fastapi import APIRouter
from fastapi.responses import FileResponse
import os

router = APIRouter()

@router.get("/chainlit/avatars/Assistant")
async def custom_avatar():
    avatar_path = os.path.join("logos", "Assistant.png")
    return FileResponse(avatar_path, media_type="image/png")

@router.get("/chainlit/logo")
async def custom_logo(theme: str = None):
    # serve a dark or light logo depending on `?theme=dark`
    filename = "dark_logo.png" if theme == "dark" else "light_logo.png"
    logo_path = os.path.join("logos", filename)
    return FileResponse(logo_path, media_type="image/png")
