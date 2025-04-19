
from fastapi import Request, HTTPException, APIRouter
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timezone
import httpx
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import asyncio
from typing import Dict, List, Optional            # ← populates os.environ from .env
from db.mongo import users_collection, notifications_collection
from notification.treeBuilder import insert_notification_into_forest
from notification.embeddings import getTextTripletEmbedding


router = APIRouter()

class NotificationRequest(BaseModel):
    text: str

async def get_current_user_by_email(request: Request) -> Optional[dict]:
    email = request.headers.get("x-user-id") or request.cookies.get("x-user-id")
    print("get_current_user_by_email email:", email)
    if not email:
        return None
    user = users_collection.find_one({"email": email})
    print(f"get_current_user_by_email user : {user}")
    return user

@router.post("/save")
async def save_notification(
    notification: NotificationRequest,
    request: Request
):
    # 1) Authenticate
    user = await get_current_user_by_email(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    print("save_notification user:", user)
    # 2) Insert skeleton document
    now = datetime.now(timezone.utc)
    skeleton = {
        "message":      notification.text,
        "email":        user["email"],
        "tree_leaf_id": None,
        "timestamp":    now,
    }
    insert_result = await asyncio.to_thread(
        notifications_collection.insert_one,
        skeleton
    )
    print("insert_result:", insert_result)
    notif_id = insert_result.inserted_id
    skeleton["_id"]         = str(notif_id)
    skeleton["tree_leaf_id"] = None

    # 3) Kick off embedding + tree‑insert in background
    async def _work():
        emb =  getTextTripletEmbedding(notification.text, alpha=0.5)
        leaf_id = insert_notification_into_forest(
            notif_id,
            notification.text,
            internal_threshold_base=0.59,
            k=3,
            max_trees=5,
        )
        # patch the Atlas doc
        await asyncio.to_thread(
            notifications_collection.update_one,
            {"_id": notif_id},
            {"$set": {"embedding": emb, "tree_leaf_id": leaf_id}}
        )
    print("before insertion to tree")
    # schedule _work() but don’t await it
    asyncio.create_task(_work())
    print("after insertion to tree")
    # 4) Return immediately
    return {
        "success":         True,
        "notification_id": str(notif_id),
        "notification":    skeleton
    }
