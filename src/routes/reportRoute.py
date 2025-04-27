from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from bson import ObjectId
from gridfs import GridFS, GridFSBucket, NoFile
from datetime import datetime
from urllib.parse import quote
import re
import unicodedata
from pathlib import Path
from db.mongo import reportDB, users_collection

router = APIRouter()
fs = GridFS(reportDB)
bucket = GridFSBucket(reportDB)
report_collection = reportDB["reports"]

def sanitize_filename(filename: str) -> str:
    # 1) Normalize unicode → NFKD, strip accents
    name = unicodedata.normalize("NFKD", filename)
    name = name.encode("ascii", "ignore").decode("ascii")
    # 2) Only allow alphanumerics, dot, underscore or hyphen; replace the rest
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    # 3) Drop any path components (just in case)
    return Path(name).name


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
async def upload_pdf(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    # Sanitize the incoming filename
    safe_name = sanitize_filename(file.filename)
    # Force a .pdf extension
    if not safe_name.lower().endswith(".pdf"):
        safe_name = safe_name + ".pdf"

    contents = await file.read()
    file_id = fs.put(contents, filename=safe_name)

    report_collection.insert_one({
        "filename": safe_name,
        "file_id": file_id,
        "email": current_user["email"],
        "uploaded_at": datetime.utcnow()
    })

    return {"id": str(file_id)}


@router.get("/preview/{file_id}")
def preview_pdf(file_id: str, current_user=Depends(get_current_user)):
    oid = ObjectId(file_id)

    # enforce ownership
    meta = report_collection.find_one({
        "file_id": oid,
        "email": current_user["email"]
    })
    if not meta:
        raise HTTPException(404, "File not found")

    try:
        stream = bucket.open_download_stream(oid)
    except NoFile:
        raise HTTPException(404, "File not found")

    filename = meta["filename"]
    fn_quoted = quote(filename, safe="")
    disposition = (
        f'inline; filename="{fn_quoted}"; '
        f"filename*=UTF-8''{fn_quoted}"
    )

    chunk_size = 1024 * 256
    return StreamingResponse(
        iter(lambda: stream.read(chunk_size), b""),
        media_type="application/pdf",
        headers={"Content-Disposition": disposition}
    )


@router.get("/download/{file_id}")
def download_pdf(file_id: str, current_user=Depends(get_current_user)):
    oid = ObjectId(file_id)

    # enforce ownership
    meta = report_collection.find_one({
        "file_id": oid,
        "email": current_user["email"]
    })
    if not meta:
        raise HTTPException(404, "File not found")

    try:
        stream = bucket.open_download_stream(oid)
    except NoFile:
        raise HTTPException(404, "File not found")

    filename = meta["filename"]
    fn_quoted = quote(filename, safe="")
    disposition = (
        f'attachment; filename="{fn_quoted}"; '
        f"filename*=UTF-8''{fn_quoted}"
    )

    chunk_size = 1024 * 256
    return StreamingResponse(
        iter(lambda: stream.read(chunk_size), b""),
        media_type="application/pdf",
        headers={"Content-Disposition": disposition}
    )


@router.get("/public/preview/{file_id}")
def public_preview_pdf(file_id: str):
    oid = ObjectId(file_id)
    try:
        stream = bucket.open_download_stream(oid)
    except NoFile:
        raise HTTPException(404, "File not found")

    filename = stream.filename or "file.pdf"
    fn_quoted = quote(filename, safe="")
    disposition = (
        f'inline; filename="{fn_quoted}"; '
        f"filename*=UTF-8''{fn_quoted}"
    )

    chunk_size = 1024 * 256
    return StreamingResponse(
        iter(lambda: stream.read(chunk_size), b""),
        media_type="application/pdf",
        headers={"Content-Disposition": disposition}
    )
