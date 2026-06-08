"""Ingest endpoints (handoff §8). Upload returns immediately with a job id; the
heavy parse/embed runs in a background task so a big textbook never times out the
request (handoff §4.10). Re-uploading a filename replaces it (handoff §4.9).
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..levels import normalize_level
from ..services import store
from ..services.rag import ingest_document

router = APIRouter()
log = logging.getLogger("physicsta.ingest")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("")
async def ingest(
    background: BackgroundTasks,
    document: UploadFile = File(...),
    docType: str = Form("notes"),
    level: str = Form(None),
    db: AsyncSession = Depends(get_session),
):
    lvl = normalize_level(level)
    file_name = document.filename or "upload.pdf"
    temp_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{os.path.basename(file_name)}")
    try:
        with open(temp_path, "wb") as f:
            f.write(await document.read())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    doc = await store.upsert_document(db, file_name, docType, lvl, status="queued")
    # Async ingestion: schedule and return a job id immediately.
    background.add_task(ingest_document, doc.id, temp_path, file_name, docType, lvl)
    return {"success": True, "fileName": file_name, "level": lvl, "documentId": doc.id, "status": "queued", "chunksAdded": 0}


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_session)):
    s = await store.stats(db)
    return {"totalChunks": s["totalChunks"], "documents": s["documents"]}


@router.delete("/document/{file_name:path}")
async def delete_document(file_name: str, db: AsyncSession = Depends(get_session)):
    from urllib.parse import unquote

    name = unquote(file_name)
    try:
        await store.delete_document(db, name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")
    return {"success": True, "deleted": name}


@router.delete("/clear")
async def clear(db: AsyncSession = Depends(get_session)):
    try:
        await store.clear_kb(db)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
    return {"success": True}
