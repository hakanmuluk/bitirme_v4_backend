# controllers/loginController.py

import secrets
import bcrypt
from fastapi import Request, Response, HTTPException, Form
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from db.mongo import db  # Import the shared db from db.py

users_collection = db["users"]

def generate_session_token() -> str:
    return secrets.token_hex(64)

async def login_user_api(request: Request, response: Response, email: str, password: str):
    # 1) Fetch user in threadpool
    user = await run_in_threadpool(
        users_collection.find_one,
        {"email": email}
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # 2) Check password off the event loop
    password_bytes = password.encode("utf-8")
    stored_hash = user["password"].encode("utf-8")
    password_ok = await run_in_threadpool(bcrypt.checkpw, password_bytes, stored_hash)
    if not password_ok:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # 3) Generate and store sessionToken in threadpool
    session_token = generate_session_token()
    await run_in_threadpool(
        users_collection.update_one,
        {"_id": user["_id"]},
        {"$set": {"sessionToken": session_token}}
    )

    # 4) Return response with cookie
    res = JSONResponse({"message": "Login successful!"})
    res.set_cookie(
      key="session",
      value=session_token,
      httponly=True,     # keep JS from reading it
      secure=True,       # required on HTTPS (Railway)
      samesite="None",   # allow it to be sent on cross‑site fetch/ajax
      max_age=3600,
      path="/"
    )
    return res

async def logout_user_api(request: Request, response: Response):
    # 1) Read session cookie
    session_token = request.cookies.get("session")
    if session_token:
        # 2) Remove token in threadpool
        await run_in_threadpool(
            users_collection.update_one,
            {"sessionToken": session_token},
            {"$set": {"sessionToken": None}}
        )

    # 3) Clear cookies
    res = JSONResponse({"message": "Logout successful"})
    res.delete_cookie("session")
    res.delete_cookie("access_token")
    res.delete_cookie("X-Chainlit-Session-id")
    res.delete_cookie("x-user-id", path="/")
    return res
