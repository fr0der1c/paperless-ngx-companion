import asyncio
import io
import logging
import os
import re
from typing import Iterable, Sequence

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from paddleocr import PaddleOCR
from pdf2image import convert_from_bytes
from PIL import Image

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PAPERLESS_BASE_URL = os.getenv("PAPERLESS_BASE_URL", "").rstrip("/")
PAPERLESS_API_TOKEN = os.getenv("PAPERLESS_API_TOKEN", "")
PAPERLESS_LANG = os.getenv("PAPERLESS_LANG", "ch")
REQUEST_TIMEOUT = 30
MAX_TITLE_LENGTH = 80
CONTENT_LOG_PREVIEW_CHARS = 200

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

if not PAPERLESS_BASE_URL or not PAPERLESS_API_TOKEN:
    logger.warning(
        "Env PAPERLESS_BASE_URL or PAPERLESS_API_TOKEN is missing; Paperless API calls will fail"
    )

app = FastAPI()
client: httpx.AsyncClient | None = None
ocr_engine: PaddleOCR | None = None


def _extract_doc_id(doc_url: str | None) -> int | None:
    if not doc_url:
        return None
    match = re.search(r"/documents/(\d+)/", doc_url)
    if not match:
        return None
    return int(match.group(1))


async def _download_document(doc_id: int) -> tuple[bytes, str]:
    if not client:
        raise HTTPException(status_code=503, detail="HTTP client not ready")
    if not PAPERLESS_BASE_URL or not PAPERLESS_API_TOKEN:
        raise HTTPException(status_code=500, detail="Paperless API config missing")
    url = f"{PAPERLESS_BASE_URL}/api/documents/{doc_id}/download/?original=true"
    headers = {"Authorization": f"Token {PAPERLESS_API_TOKEN}"}
    resp = await client.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    return resp.content, content_type


def _is_pdf(data: bytes, content_type: str) -> bool:
    if content_type.startswith("application/pdf"):
        return True
    return data[:4] == b"%PDF"


def _images_from_bytes(data: bytes, content_type: str) -> list[Image.Image]:
    if _is_pdf(data, content_type):
        return convert_from_bytes(data)
    return [Image.open(io.BytesIO(data))]


def _ocr_image(img: Image.Image) -> list[str]:
    if not ocr_engine:
        raise RuntimeError("OCR engine not initialized")
    result = ocr_engine.ocr(np.array(img), cls=True)
    texts: list[str] = []
    for line in result:
        for _box, (txt, _score) in line:
            cleaned = txt.strip()
            if cleaned:
                texts.append(cleaned)
    return texts


def _build_content(texts: Iterable[str]) -> str:
    return "\n".join(texts)


def _build_title(texts: Sequence[str]) -> str | None:
    for txt in texts:
        if txt:
            return txt[:MAX_TITLE_LENGTH]
    return None


def _preview(text: str, limit: int = CONTENT_LOG_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


async def _update_document(doc_id: int, content: str, title: str | None) -> None:
    if not client:
        raise HTTPException(status_code=503, detail="HTTP client not ready")
    if not PAPERLESS_BASE_URL or not PAPERLESS_API_TOKEN:
        raise HTTPException(status_code=500, detail="Paperless API config missing")
    url = f"{PAPERLESS_BASE_URL}/api/documents/{doc_id}/"
    headers = {
        "Authorization": f"Token {PAPERLESS_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"content": content}
    if title:
        payload["title"] = title
    resp = await client.patch(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


@app.on_event("startup")
async def _startup() -> None:
    global client, ocr_engine
    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    client = httpx.AsyncClient(timeout=timeout)
    loop = asyncio.get_running_loop()
    ocr_engine = await loop.run_in_executor(
        None, lambda: PaddleOCR(use_angle_cls=True, lang=PAPERLESS_LANG)
    )
    logger.info("OCR engine initialized, lang=%s", PAPERLESS_LANG)


@app.on_event("shutdown")
async def _shutdown() -> None:
    global client
    if client:
        await client.aclose()
        client = None


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/paperless-webhook")
async def paperless_webhook(request: Request) -> JSONResponse:
    if not client:
        raise HTTPException(status_code=503, detail="HTTP client not ready")
    body = await request.json()
    doc_url = body.get("doc_url") or body.get("url")
    doc_id = _extract_doc_id(doc_url)
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id not found")

    logger.info("Webhook received doc_id=%s doc_url=%s", doc_id, doc_url)
    try:
        file_bytes, content_type = await _download_document(doc_id)
        images = _images_from_bytes(file_bytes, content_type)
        texts: list[str] = []
        for img in images:
            texts.extend(_ocr_image(img))
        content = _build_content(texts)
        title = _build_title(texts)
        logger.info(
            "OCR done doc_id=%s lines=%s title=%s content_preview=%s",
            doc_id,
            len(texts),
            title,
            _preview(content),
        )
        await _update_document(doc_id, content, title)
    except httpx.HTTPStatusError as exc:
        logger.exception("Paperless API call failed: %s", exc)
        raise HTTPException(status_code=502, detail="Paperless API call failed") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to process document %s", doc_id)
        raise HTTPException(status_code=500, detail="OCR processing failed") from exc

    return JSONResponse({"status": "ok", "doc_id": doc_id})
