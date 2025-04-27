from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from bson import ObjectId
from gridfs import GridFS, GridFSBucket, NoFile
from datetime import datetime
from urllib.parse import quote

from db.mongo import reportDB, users_collection

router = APIRouter()
fs = GridFS(reportDB)
bucket = GridFSBucket(reportDB)
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
async def upload_pdf(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files allowed.")
    contents = await file.read()
    file_id = fs.put(contents, filename=file.filename)

    report_collection.insert_one({
        "filename": file.filename,
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
