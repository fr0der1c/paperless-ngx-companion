import asyncio
import base64
import io
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Sequence

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pdf2image import convert_from_bytes
from PIL import Image, ImageOps

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PAPERLESS_BASE_URL = os.getenv("PAPERLESS_BASE_URL", "").rstrip("/")
PAPERLESS_API_TOKEN = os.getenv("PAPERLESS_API_TOKEN", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
LLM_REQUEST_TIMEOUT = int(os.getenv("LLM_REQUEST_TIMEOUT", "120"))
MAX_TITLE_LENGTH = 80
CONTENT_LOG_PREVIEW_CHARS = 200
PAPERLESS_PAGE_SIZE = int(os.getenv("PAPERLESS_PAGE_SIZE", "1000"))

LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.openai.com/v1").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5.5")

LLM_OCR_API_BASE = os.getenv("LLM_OCR_API_BASE", "").rstrip("/")
LLM_OCR_API_KEY = os.getenv("LLM_OCR_API_KEY", "")
LLM_OCR_MODEL = os.getenv("LLM_OCR_MODEL", "")
LLM_OCR_MAX_TOKENS = int(os.getenv("LLM_OCR_MAX_TOKENS", "4096"))
LLM_OCR_IMAGE_MAX_SIZE = int(os.getenv("LLM_OCR_IMAGE_MAX_SIZE", "2048"))
LLM_OCR_IMAGE_DETAIL = os.getenv("LLM_OCR_IMAGE_DETAIL", "high")

LLM_EXTRACT_API_BASE = os.getenv("LLM_EXTRACT_API_BASE", "").rstrip("/")
LLM_EXTRACT_API_KEY = os.getenv("LLM_EXTRACT_API_KEY", "")
LLM_EXTRACT_MODEL = os.getenv("LLM_EXTRACT_MODEL", "")
LLM_EXTRACT_INPUT_CHAR_LIMIT = int(os.getenv("LLM_EXTRACT_INPUT_CHAR_LIMIT", "12000"))
LLM_EXTRACT_MAX_TOKENS = int(os.getenv("LLM_EXTRACT_MAX_TOKENS", "1200"))

LLM_PAGE_CONCURRENCY = max(1, int(os.getenv("LLM_PAGE_CONCURRENCY", "2")))
LLM_MAX_PAGES = int(os.getenv("LLM_MAX_PAGES", "20"))

logger = logging.getLogger("paperless_ocr")


@dataclass(frozen=True)
class LLMConfig:
    purpose: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class NamedEntity:
    entity_id: int
    name: str


@dataclass(frozen=True)
class MetadataExtraction:
    title: str | None
    tags: list[str]
    document_type: str | None


def _configure_logging() -> None:
    level = logging.getLevelName(LOG_LEVEL)
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(level)
    logger.setLevel(level)
    logger.propagate = True


def _resolve_llm_config(
    purpose: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> LLMConfig:
    return LLMConfig(
        purpose=purpose,
        base_url=base_url or LLM_API_BASE,
        api_key=api_key or LLM_API_KEY,
        model=model or LLM_MODEL,
    )


OCR_LLM_CONFIG = _resolve_llm_config(
    "ocr",
    base_url=LLM_OCR_API_BASE,
    api_key=LLM_OCR_API_KEY,
    model=LLM_OCR_MODEL,
)
EXTRACT_LLM_CONFIG = _resolve_llm_config(
    "extract",
    base_url=LLM_EXTRACT_API_BASE,
    api_key=LLM_EXTRACT_API_KEY,
    model=LLM_EXTRACT_MODEL,
)

_configure_logging()

if not PAPERLESS_BASE_URL or not PAPERLESS_API_TOKEN:
    logger.warning(
        "Env PAPERLESS_BASE_URL or PAPERLESS_API_TOKEN is missing; Paperless API calls will fail"
    )

app = FastAPI()
client: httpx.AsyncClient | None = None


def _require_client() -> httpx.AsyncClient:
    if not client:
        raise HTTPException(status_code=503, detail="HTTP client not ready")
    return client


def _require_paperless_config() -> None:
    if not PAPERLESS_BASE_URL or not PAPERLESS_API_TOKEN:
        raise HTTPException(status_code=500, detail="Paperless API config missing")


def _require_llm_config(config: LLMConfig) -> None:
    missing: list[str] = []
    if not config.base_url:
        missing.append("LLM_API_BASE")
    if not config.api_key:
        missing.append(
            "LLM_API_KEY"
            if config.purpose == "extract" and not LLM_EXTRACT_API_KEY
            else f"LLM_{config.purpose.upper()}_API_KEY"
        )
    if not config.model:
        missing.append("LLM_MODEL")
    if missing:
        raise RuntimeError(
            f"Missing LLM config for {config.purpose}: {', '.join(sorted(set(missing)))}"
        )


def _paperless_headers() -> dict[str, str]:
    _require_paperless_config()
    return {"Authorization": f"Token {PAPERLESS_API_TOKEN}"}


def _extract_doc_id(doc_url: str | None) -> int | None:
    if not doc_url:
        return None
    match = re.search(r"/documents/(\d+)/", doc_url)
    if not match:
        return None
    return int(match.group(1))


async def _download_document(doc_id: int) -> tuple[bytes, str]:
    url = f"{PAPERLESS_BASE_URL}/api/documents/{doc_id}/download/?original=true"
    resp = await _require_client().get(
        url,
        headers=_paperless_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("content-type", "")


async def _get_document_details(doc_id: int) -> dict[str, Any]:
    url = f"{PAPERLESS_BASE_URL}/api/documents/{doc_id}/"
    resp = await _require_client().get(
        url,
        headers=_paperless_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected document payload from Paperless")
    return data


async def _list_paginated(endpoint: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_url = f"{PAPERLESS_BASE_URL}{endpoint}"
    params: dict[str, Any] | None = {"page_size": PAPERLESS_PAGE_SIZE}

    while next_url:
        resp = await _require_client().get(
            next_url,
            headers=_paperless_headers(),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    items.append(item)
            break

        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected list payload from {endpoint}")

        results = data.get("results")
        if not isinstance(results, list):
            raise RuntimeError(f"Missing results in paginated payload from {endpoint}")

        for item in results:
            if isinstance(item, dict):
                items.append(item)

        next_url = data.get("next")
        params = None

    return items


def _to_named_entities(items: list[dict[str, Any]]) -> list[NamedEntity]:
    entities: list[NamedEntity] = []
    for item in items:
        entity_id = item.get("id")
        name = item.get("name")
        if isinstance(entity_id, int) and isinstance(name, str) and name.strip():
            entities.append(NamedEntity(entity_id=entity_id, name=name.strip()))
    return entities


async def _list_existing_tags() -> list[NamedEntity]:
    return _to_named_entities(await _list_paginated("/api/tags/"))


async def _list_existing_document_types() -> list[NamedEntity]:
    return _to_named_entities(await _list_paginated("/api/document_types/"))


def _is_pdf(data: bytes, content_type: str) -> bool:
    if content_type.startswith("application/pdf"):
        return True
    return data[:4] == b"%PDF"


def _images_from_bytes(data: bytes, content_type: str) -> list[Image.Image]:
    if _is_pdf(data, content_type):
        return convert_from_bytes(data)

    image = Image.open(io.BytesIO(data))
    image.load()
    return [image]


def _prepare_image_for_llm(img: Image.Image) -> str:
    image = ImageOps.exif_transpose(img)
    if image.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", image.size, (255, 255, 255))
        alpha = image.getchannel("A")
        background.paste(image.convert("RGB"), mask=alpha)
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    width, height = image.size
    longest_edge = max(width, height)
    if LLM_OCR_IMAGE_MAX_SIZE > 0 and longest_edge > LLM_OCR_IMAGE_MAX_SIZE:
        scale = LLM_OCR_IMAGE_MAX_SIZE / longest_edge
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _preview(text: str, limit: int = CONTENT_LOG_PREVIEW_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _sanitize_title(title: str | None) -> str | None:
    if not title:
        return None
    cleaned = re.sub(r"\s+", " ", title).strip().strip("\"'`")
    if not cleaned:
        return None
    return cleaned[:MAX_TITLE_LENGTH]


def _build_fallback_title(content: str) -> str | None:
    for line in content.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned:
            return cleaned[:MAX_TITLE_LENGTH]
    return None


def _build_content(page_texts: Sequence[str]) -> str:
    pages = [page.strip() for page in page_texts if page.strip()]
    return "\n\n".join(pages)


def _extract_message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("LLM response missing choices")

    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        raise RuntimeError("LLM response missing message")

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    texts.append(text)
        joined = "\n".join(texts).strip()
        if joined:
            return joined

    raise RuntimeError("LLM response content is empty")


def _strip_json_fence(text: str) -> str:
    fenced = text.strip()
    if fenced.startswith("```"):
        fenced = re.sub(r"^```(?:json)?\s*", "", fenced)
        fenced = re.sub(r"\s*```$", "", fenced)
    return fenced.strip()


async def _call_chat_completion(
    config: LLMConfig,
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
) -> str:
    _require_llm_config(config)
    url = f"{config.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    resp = await _require_client().post(
        url,
        json=payload,
        headers=headers,
        timeout=LLM_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("LLM response must be a JSON object")
    return _extract_message_content(data)


async def _ocr_page_with_llm(img: Image.Image, page_index: int) -> str:
    image_url = _prepare_image_for_llm(img)
    messages = [
        {
            "role": "system",
            "content": (
                "You are an OCR engine. Transcribe the document page exactly in reading order. "
                "Do not summarize, explain, classify, or add missing information. "
                "Return plain text only."
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Please OCR page {page_index}. "
                        "Preserve visible wording as faithfully as possible."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url,
                        "detail": LLM_OCR_IMAGE_DETAIL,
                    },
                },
            ],
        },
    ]
    return await _call_chat_completion(
        OCR_LLM_CONFIG,
        messages=messages,
        max_tokens=LLM_OCR_MAX_TOKENS,
        temperature=0.0,
    )


async def _ocr_images_with_llm(images: Sequence[Image.Image]) -> list[str]:
    if not images:
        return []
    if LLM_MAX_PAGES > 0 and len(images) > LLM_MAX_PAGES:
        raise RuntimeError(
            f"Document has {len(images)} pages, exceeds LLM_MAX_PAGES={LLM_MAX_PAGES}"
        )

    semaphore = asyncio.Semaphore(LLM_PAGE_CONCURRENCY)

    async def _run_one(index: int, image: Image.Image) -> str:
        async with semaphore:
            logger.info("Start LLM OCR page=%s", index)
            text = await _ocr_page_with_llm(image, index)
            logger.info("Finished LLM OCR page=%s chars=%s", index, len(text))
            return text.strip()

    tasks = [
        asyncio.create_task(_run_one(index, image))
        for index, image in enumerate(images, start=1)
    ]
    return await asyncio.gather(*tasks)


async def _extract_metadata_with_llm(
    content: str,
    allowed_tags: Sequence[NamedEntity],
    allowed_document_types: Sequence[NamedEntity],
) -> MetadataExtraction:
    if not content.strip():
        return MetadataExtraction(title=None, tags=[], document_type=None)

    text = content[:LLM_EXTRACT_INPUT_CHAR_LIMIT]
    tag_names = [item.name for item in allowed_tags]
    document_type_names = [item.name for item in allowed_document_types]
    schema_hint = {
        "title": "string or null",
        "tags": ["must be chosen from allowed_tags only"],
        "document_type": "string or null, must be chosen from allowed_document_types only",
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Extract metadata from OCR text. "
                "Return a JSON object only. "
                "Choose tags only from allowed_tags. "
                "Choose document_type only from allowed_document_types. "
                "If no tag is suitable, return an empty array. "
                "If no document type is suitable, return null. "
                "Do not invent labels."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "allowed_tags": tag_names,
                    "allowed_document_types": document_type_names,
                    "output_schema": schema_hint,
                    "ocr_text": text,
                },
                ensure_ascii=False,
            ),
        },
    ]

    raw = await _call_chat_completion(
        EXTRACT_LLM_CONFIG,
        messages=messages,
        max_tokens=LLM_EXTRACT_MAX_TOKENS,
        temperature=0.0,
    )
    payload = json.loads(_strip_json_fence(raw))
    if not isinstance(payload, dict):
        raise RuntimeError("Metadata extraction response must be a JSON object")

    raw_title = payload.get("title")
    raw_tags = payload.get("tags")
    raw_document_type = payload.get("document_type")

    tags: list[str] = []
    if isinstance(raw_tags, list):
        for item in raw_tags:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if cleaned and cleaned not in tags:
                tags.append(cleaned)

    return MetadataExtraction(
        title=_sanitize_title(raw_title if isinstance(raw_title, str) else None),
        tags=tags,
        document_type=(
            raw_document_type.strip()
            if isinstance(raw_document_type, str) and raw_document_type.strip()
            else None
        ),
    )


def _build_name_index(entities: Sequence[NamedEntity]) -> dict[str, NamedEntity]:
    index: dict[str, NamedEntity] = {}
    for entity in entities:
        key = entity.name.strip().casefold()
        if key and key not in index:
            index[key] = entity
    return index


def _validate_selected_tags(
    selected_names: Sequence[str],
    allowed_tags: Sequence[NamedEntity],
) -> list[int]:
    allowed_index = _build_name_index(allowed_tags)
    validated_ids: list[int] = []
    seen: set[int] = set()
    for name in selected_names:
        entity = allowed_index.get(name.strip().casefold())
        if not entity or entity.entity_id in seen:
            continue
        validated_ids.append(entity.entity_id)
        seen.add(entity.entity_id)
    return validated_ids


def _validate_selected_document_type(
    selected_name: str | None,
    allowed_document_types: Sequence[NamedEntity],
) -> int | None:
    if not selected_name:
        return None
    allowed_index = _build_name_index(allowed_document_types)
    entity = allowed_index.get(selected_name.strip().casefold())
    if not entity:
        return None
    return entity.entity_id


def _extract_existing_tag_ids(document: dict[str, Any]) -> list[int]:
    tags = document.get("tags")
    if not isinstance(tags, list):
        return []

    tag_ids: list[int] = []
    for item in tags:
        if isinstance(item, int):
            tag_ids.append(item)
            continue
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            tag_ids.append(item["id"])
    return tag_ids


async def _update_document(
    doc_id: int,
    *,
    content: str,
    title: str | None,
    tag_ids: Sequence[int] | None,
    document_type_id: int | None,
) -> None:
    url = f"{PAPERLESS_BASE_URL}/api/documents/{doc_id}/"
    headers = {
        **_paperless_headers(),
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {"content": content}
    if title:
        payload["title"] = title
    if tag_ids is not None:
        payload["tags"] = list(tag_ids)
    if document_type_id is not None:
        payload["document_type"] = document_type_id

    resp = await _require_client().patch(
        url,
        json=payload,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()


@app.on_event("startup")
async def _startup() -> None:
    global client
    timeout = httpx.Timeout(max(REQUEST_TIMEOUT, LLM_REQUEST_TIMEOUT))
    client = httpx.AsyncClient(timeout=timeout)
    logger.info(
        "LLM OCR configured ocr_model=%s extract_model=%s",
        OCR_LLM_CONFIG.model,
        EXTRACT_LLM_CONFIG.model,
    )


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
    _require_client()
    body = await request.json()
    doc_url = body.get("doc_url") or body.get("url")
    doc_id = _extract_doc_id(doc_url)
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id not found")

    logger.info("Webhook received doc_id=%s doc_url=%s", doc_id, doc_url)
    try:
        file_bytes, content_type = await _download_document(doc_id)
        images = _images_from_bytes(file_bytes, content_type)
        page_texts = await _ocr_images_with_llm(images)
        content = _build_content(page_texts)
        if not content:
            raise RuntimeError("OCR returned empty content")

        logger.info(
            "LLM OCR done doc_id=%s pages=%s content_preview=%s",
            doc_id,
            len(page_texts),
            _preview(content),
        )

        document_details, allowed_tags, allowed_document_types = await asyncio.gather(
            _get_document_details(doc_id),
            _list_existing_tags(),
            _list_existing_document_types(),
        )

        title = _build_fallback_title(content)
        selected_tag_ids: list[int] = []
        document_type_id: int | None = None
        try:
            metadata = await _extract_metadata_with_llm(
                content,
                allowed_tags,
                allowed_document_types,
            )
            title = metadata.title or title
            selected_tag_ids = _validate_selected_tags(metadata.tags, allowed_tags)
            document_type_id = _validate_selected_document_type(
                metadata.document_type,
                allowed_document_types,
            )
            logger.info(
                "Metadata extracted doc_id=%s title=%s selected_tags=%s document_type_id=%s",
                doc_id,
                title,
                selected_tag_ids,
                document_type_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Metadata extraction failed for doc_id=%s: %s", doc_id, exc)

        existing_tag_ids = _extract_existing_tag_ids(document_details)
        merged_tag_ids: list[int] | None = None
        if selected_tag_ids:
            merged_tag_ids = sorted(set(existing_tag_ids) | set(selected_tag_ids))

        await _update_document(
            doc_id,
            content=content,
            title=title,
            tag_ids=merged_tag_ids,
            document_type_id=document_type_id,
        )
    except httpx.HTTPStatusError as exc:
        logger.exception("Paperless or LLM API call failed: %s", exc)
        raise HTTPException(status_code=502, detail="Upstream API call failed") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to process document %s", doc_id)
        raise HTTPException(status_code=500, detail="OCR processing failed") from exc

    return JSONResponse({"status": "ok", "doc_id": doc_id})
