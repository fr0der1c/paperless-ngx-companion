import argparse
import asyncio
import faulthandler
import logging
import os
import time
from pathlib import Path

import httpx

import app

faulthandler.enable()
os.environ.setdefault("PYTHONFAULTHANDLER", "1")


def _load_images(file_path: Path) -> list:
    data = file_path.read_bytes()
    content_type = "application/pdf" if file_path.suffix.lower() == ".pdf" else ""
    return app._images_from_bytes(data, content_type)


async def _run(file_path: Path) -> None:
    images = _load_images(file_path)
    if not images:
        app.logger.warning("No images detected from file=%s", file_path)
        return

    created_client = False
    if not app.client:
        timeout = httpx.Timeout(max(app.REQUEST_TIMEOUT, app.LLM_REQUEST_TIMEOUT))
        app.client = httpx.AsyncClient(timeout=timeout)
        created_client = True

    app.logger.info("Loaded %s image(s) from %s", len(images), file_path)
    started = time.perf_counter()
    try:
        page_texts = await app._ocr_images_with_llm(images)
    finally:
        if created_client and app.client:
            await app.client.aclose()
            app.client = None

    total_cost = time.perf_counter() - started
    for idx, page_text in enumerate(page_texts, start=1):
        line_count = len([line for line in page_text.splitlines() if line.strip()])
        header = f"--- Page {idx} ({line_count} lines) ---"
        print(header, flush=True)
        if page_text.strip():
            print(page_text.strip(), flush=True)
        app.logger.info("Finished OCR page %s chars=%s", idx, len(page_text))

    combined = app._build_content(page_texts)
    app.logger.info(
        "Local LLM OCR finished pages=%s chars=%s in %.2fs",
        len(page_texts),
        len(combined),
        total_cost,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run OCR on a local file using multimodal LLM OCR"
    )
    parser.add_argument("file", type=Path, help="path to an image or PDF file")
    parser.add_argument(
        "--log-level",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="logging level",
    )
    args = parser.parse_args()

    log_level = getattr(logging, args.log_level)
    logging.getLogger().setLevel(log_level)
    app.logger.setLevel(log_level)

    try:
        asyncio.run(_run(args.file))
    finally:
        app.logger.info("local_ocr_test finished")


if __name__ == "__main__":
    main()
