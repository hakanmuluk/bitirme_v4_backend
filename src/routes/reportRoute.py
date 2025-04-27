from fastapi import FastAPI, File, UploadFile, HTTPException, APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pymongo import MongoClient
from bson import ObjectId
from gridfs import GridFS, NoFile
from datetime import datetime
from db.mongo import reportDB, users_collection
from urllib.parse import quote

fs = GridFS(reportDB)
router = APIRouter()

report_collection = reportDB["reports"]

async def get_current_user(request: Request):
    email = request.headers.get("x-user-id") or request.cookies.get("x-user-id")
    if not email:
        raise HTTPException(401, "Unauthorized")
    user = users_collection.find_one({"email": email})
    if not user:
        raise HTTPException(401, "Unauthorized")
    return user

@router.get("/reports")
async def get_user_reports(current_user=Depends(get_current_user)):
    """
    Return all reports belonging to the current user.
    """
    return [
        {
            "id": str(doc["file_id"]),
            "name": doc["filename"]
        }
        for doc in report_collection.find({"email": current_user["email"]})
    ]

@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...), current_user = Depends(get_current_user)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files allowed.")
    contents = await file.read()
    file_id = fs.put(contents, filename=file.filename)

    # Save metadata + associate with user.email
    report_collection.insert_one({
        "filename": file.filename,
        "file_id": file_id,
        "email": current_user["email"],
        "uploaded_at":  datetime.utcnow()
    })

    return {"id": str(file_id)}

@router.get("/preview/{file_id}")
def preview_pdf(file_id: str, current_user = Depends(get_current_user)):
    oid = ObjectId(file_id)

    # enforce ownership
    meta = report_collection.find_one({
        "file_id": oid,
        "email": current_user["email"]
    })
    if not meta:
        raise HTTPException(404, "File not found")

    try:
        grid_out = fs.get(oid)
    except NoFile:
        raise HTTPException(404, "File not found")

    return StreamingResponse(
        grid_out,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{meta["filename"]}"'
        }
    )

# ─── Download endpoint (attachment, only if user owns it) ───────
@router.get("/download/{file_id}")
def download_pdf(file_id: str, current_user = Depends(get_current_user)):
    oid = ObjectId(file_id)

    # enforce ownership
    meta = report_collection.find_one({
        "file_id": oid,
        "email": current_user["email"]
    })
    if not meta:
        raise HTTPException(404, "File not found")

    try:
        grid_out = fs.get(oid)
    except NoFile:
        raise HTTPException(404, "File not found")

    return StreamingResponse(
        grid_out,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{meta["filename"]}"'
        }
    )

@router.get("/public/preview/{file_id}")
def public_preview_pdf(file_id: str):
    oid = ObjectId(file_id)

    try:
        grid_out = fs.get(oid)
    except NoFile:
        raise HTTPException(404, "File not found")

    # percent-encode in UTF-8
    fn = grid_out.filename
    fn_quoted = quote(fn, safe="")
    disposition = (
        f"inline;"
        f' filename="{fn_quoted}"'          # fallback ASCII-only
        f"; filename*=UTF-8''{fn_quoted}"   # RFC 5987
    )

    return StreamingResponse(
        grid_out,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition}
    )



