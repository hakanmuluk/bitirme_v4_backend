# controllers/favoriteController.py

import secrets
from bson import ObjectId
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from db.mongo import db  # assumes db.py exposes `db`

users_collection = db["users"]

async def add_favorite_company_api(request: Request, company: str):
    session_token = request.cookies.get("session")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 1) Find user offloaded to threadpool
    user = await run_in_threadpool(
        users_collection.find_one, {"sessionToken": session_token}
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    # 2) Update favorites offloaded
    await run_in_threadpool(
        users_collection.update_one,
        {"_id": user["_id"]},
        {"$addToSet": {"favoriteCompanies": company}}
    )

    # 3) Retrieve updated list offloaded
    updated = await run_in_threadpool(
        users_collection.find_one,
        {"_id": user["_id"]},
        {"favoriteCompanies": 1, "_id": 0}
    )

    return JSONResponse({
        "message": f"Added '{company}' to favorites.",
        "favoriteCompanies": updated.get("favoriteCompanies", [])
    })


async def remove_favorite_company_api(request: Request, company: str):
    session_token = request.cookies.get("session")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await run_in_threadpool(
        users_collection.find_one, {"sessionToken": session_token}
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    await run_in_threadpool(
        users_collection.update_one,
        {"_id": user["_id"]},
        {"$pull": {"favoriteCompanies": company}}
    )

    updated = await run_in_threadpool(
        users_collection.find_one,
        {"_id": user["_id"]},
        {"favoriteCompanies": 1, "_id": 0}
    )

    return JSONResponse({
        "message": f"Removed '{company}' from favorites.",
        "favoriteCompanies": updated.get("favoriteCompanies", [])
    })


async def get_favorite_companies_api(request: Request):
    session_token = request.cookies.get("session")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await run_in_threadpool(
        users_collection.find_one, {"sessionToken": session_token}
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    favorites = user.get("favoriteCompanies", [])
    return JSONResponse({
        "favoriteCompanies": favorites
    })
