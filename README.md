# paperless-ngx paddleocr webhook service

English | 中文

## Overview
Small FastAPI service that handles Paperless-ngx workflow webhooks (Document Added), downloads the original document, runs PaddleOCR to extract text, generates a simple title, and PATCHes the document content/title back to Paperless-ngx via REST API.

## Features
- Receive webhook at `/paperless-webhook`, extract `doc_id` from `doc_url`.
- Download original file (`/api/documents/{id}/download/?original=true`).
- Auto-detect PDF vs. image; for PDF, convert to images via pdf2image (poppler).
- Run PaddleOCR once per process (configurable language).
- Build full text and a short title (first non-empty line, max 80 chars), PATCH back to Paperless.
- Health check at `/healthz`.

## Requirements
- Docker build uses `python:3.11-slim`, installs `poppler-utils`, `libgl1`, `libglib2.0-0`.
- Internet access to pull Python wheels during build (paddleocr, paddlepaddle, pdf2image etc.).
- Paperless-ngx API token (Token Auth).

## Environment variables
- `PAPERLESS_BASE_URL` (required): e.g. `http://webserver:8000`
- `PAPERLESS_API_TOKEN` (required): Paperless API token (Authorization: Token …)
- `PAPERLESS_LANG` (optional): PaddleOCR language code, default `ch`.
- `LOG_LEVEL` (optional): logging level, default `INFO`.

## Build and run (Docker)
```sh
docker build -t paperless-ocr .
docker run -p 8000:8000 \
  -e PAPERLESS_BASE_URL=http://webserver:8000 \
  -e PAPERLESS_API_TOKEN=YOUR_TOKEN \
  -e PAPERLESS_LANG=ch \
  paperless-ocr
```

## Paperless workflow setup
1. Create a workflow with trigger **Document Added**.
2. Action: **Webhook**.
3. URL: `http://<host>:8000/paperless-webhook`
4. Body: JSON including `doc_url` (or `url`), e.g.
   ```json
   {
     "doc_url": "{{ doc_url }}",
     "title": "{{ doc_title }}",
     "filename": "{{ filename }}"
   }
   ```
5. The service will parse `doc_url` for `/documents/{id}/`, download the original file, run OCR, and PATCH `content`/`title`.

## Endpoints
- `POST /paperless-webhook`: main entrypoint.
- `GET /healthz`: returns `{"status": "ok"}`.

## Add to your paperless-ngx docker-compose
Place this service in the same Docker network as Paperless (`webserver` below is the Paperless API host). If you build locally from this repo:
```yaml
services:
  ocr-service:
    build: ./paperless-ngx-paddleocr   # or image: paperless-ocr:latest if pre-built
    environment:
      PAPERLESS_BASE_URL: http://webserver:8000
      PAPERLESS_API_TOKEN: ${PAPERLESS_API_TOKEN}
      PAPERLESS_LANG: ch
    depends_on:
      - webserver
    restart: unless-stopped
    networks:
      - paperless

networks:
  paperless:
    external: true   # reuse the network where Paperless runs; or omit if you use the default project network
```
Then configure the Paperless workflow webhook URL as `http://ocr-service:8000/paperless-webhook`.

## Notes
- Title generation is minimal (first non-empty line, truncated to 80 chars). Extend as needed (LLM, tagging, etc.).
- If you add a second workflow with trigger **Document Updated**, add a tag or custom field filter to avoid self-trigger loops.
- The service expects Paperless API token and base URL; missing configuration will return 500/503.
- PaddleOCR downloads models on first run. If your runtime has no internet/SSL issues, mount a pre-downloaded model directory: run locally `python - <<'PY'\nfrom paddleocr import PaddleOCR\nPaddleOCR(use_angle_cls=True, lang=\"ch\")\nPY`, then volume-mount the produced `~/.paddleocr` into the container (e.g. `-v ~/.paddleocr:/home/appuser/.paddleocr`).

---

# paperless-ngx paddleocr webhook 服务

## 概述
基于 FastAPI 的轻量服务，接收 Paperless-ngx Workflow Webhook（Document Added），下载原文件，用 PaddleOCR 识别全文，生成简单标题，并通过 REST API 回写 Paperless 的 `content/title`。

## 功能
- `/paperless-webhook` 接收 webhook，从 `doc_url` 提取 `doc_id`。
- 下载原始文件（`/api/documents/{id}/download/?original=true`）。
- 自动区分 PDF 与图片，PDF 经 pdf2image（poppler）转图后识别。
- PaddleOCR 进程级初始化一次（语言可配置）。
- 拼接全文，取首个非空行作为标题（最长 80 字），PATCH 回 Paperless。
- `/healthz` 健康检查。

## 依赖环境
- Docker 基于 `python:3.11-slim`，安装 `poppler-utils`、`libgl1`、`libglib2.0-0`。
- 构建阶段需能下载 Python 依赖（paddleocr、paddlepaddle、pdf2image 等）。
- 需要 Paperless-ngx 的 API Token（Token Auth）。

## 环境变量
- `PAPERLESS_BASE_URL`（必填）：如 `http://webserver:8000`
- `PAPERLESS_API_TOKEN`（必填）：Paperless API token（Authorization: Token …）
- `PAPERLESS_LANG`（可选）：PaddleOCR 语言代码，默认 `ch`
- `LOG_LEVEL`（可选）：日志级别，默认 `INFO`

## 构建与运行（Docker）
```sh
docker build -t paperless-ocr .
docker run -p 8000:8000 \
  -e PAPERLESS_BASE_URL=http://webserver:8000 \
  -e PAPERLESS_API_TOKEN=YOUR_TOKEN \
  -e PAPERLESS_LANG=ch \
  paperless-ocr
```

## Paperless 工作流配置
1. 新建 Workflow，触发器选 **Document Added**。
2. 动作选 **Webhook**。
3. URL: `http://<host>:8000/paperless-webhook`
4. Body 选 JSON，包含 `doc_url`（或 `url`），示例：
   ```json
   {
     "doc_url": "{{ doc_url }}",
     "title": "{{ doc_title }}",
     "filename": "{{ filename }}"
   }
   ```
5. 服务会从 `doc_url` 解析 `/documents/{id}/`，下载原文件，OCR 后 PATCH 回 `content/title`。

## 接口
- `POST /paperless-webhook`: 主入口
- `GET /healthz`: 返回 `{"status": "ok"}`

## 如何加入你的 paperless-ngx docker-compose
让该服务与 Paperless 处于同一网络（下方 `webserver` 为 Paperless API 主机）。如果从当前仓库构建：
```yaml
services:
  ocr-service:
    build: ./paperless-ngx-paddleocr   # 若已构建好镜像则用 image: paperless-ocr:latest
    environment:
      PAPERLESS_BASE_URL: http://webserver:8000
      PAPERLESS_API_TOKEN: ${PAPERLESS_API_TOKEN}
      PAPERLESS_LANG: ch
    depends_on:
      - webserver
    restart: unless-stopped
    networks:
      - paperless

networks:
  paperless:
    external: true   # 复用 Paperless 所在网络；若使用默认项目网络可省略
```
然后在 Paperless Workflow 的 Webhook URL 中填写 `http://ocr-service:8000/paperless-webhook`。

## 说明
- 标题生成策略很简单（首个非空行截断 80 字符）；可按需扩展（LLM、标签生成等）。
- 若再用 **Document Updated** 触发，请加标签或自定义字段过滤，避免自触发循环。
- 缺少 API Token 或 Base URL 将返回 500/503，请确保环境变量配置正确。
- PaddleOCR 首次运行会下载模型。如运行环境无法联网或有 SSL 问题，可先在本机执行 `python - <<'PY'\nfrom paddleocr import PaddleOCR\nPaddleOCR(use_angle_cls=True, lang=\"ch\")\nPY` 下载模型，再把生成的 `~/.paddleocr` 挂载到容器（如 `-v ~/.paddleocr:/home/appuser/.paddleocr`）。
