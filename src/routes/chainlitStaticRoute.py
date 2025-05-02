# routes/chainlitStaticRoute.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter()

# __file__ points to .../src/routes/chainlitStaticRoute.py
BASE_DIR = Path(__file__).resolve().parent.parent    # => .../src
LOGOS_DIR = BASE_DIR / "logos"

@router.get("/chainlit/avatars/Assistant")
async def custom_avatar():
    avatar_file = LOGOS_DIR / "Assistant.png"
    if not avatar_file.is_file():
        raise HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(str(avatar_file), media_type="image/png")

@router.get("/chainlit/logo")
async def custom_logo(theme: str = None):
    filename = "dark_logo.png" if theme == "dark" else "light_logo.png"
    logo_file = LOGOS_DIR / filename
    if not logo_file.is_file():
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(str(logo_file), media_type="image/png")
