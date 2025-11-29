# paperless-ngx companion (OCR webhook)

English | 中文

## Overview
Paperless-ngx is a great self-hosted DMS, but its built-in Tesseract OCR can be limited. PaddleOCR offers stronger recognition, and an LLM can produce better titles and fix OCR formatting issues. This project uses Paperless-ngx native Workflow + Webhook to attach external OCR and overwrite the built-in OCR result.

This is a lightweight FastAPI service that listens to the Paperless-ngx “Document Added” webhook, downloads the original file, runs PaddleOCR for text, optionally uses an LLM to generate a title (and reformat OCR line breaks/spacing), then PATCHes `content/title` back via the Paperless REST API.

## Features
- Receive webhook at `/paperless-webhook`, extract `doc_id` from `doc_url`.
- Download original file (`/api/documents/{id}/download/?original=true`).
- Auto-detect PDF vs. image; for PDF, convert to images via pdf2image (poppler).
- Run PaddleOCR once per process (configurable language).
- Build full text; optional LLM title generation; optional LLM-based line-break/spacing fix (no semantic changes); PATCH back to Paperless.
- Health check at `/healthz`.

## Requirements
- Docker build uses `python:3.10-slim`, installs `poppler-utils`, `libgl1`, `libglib2.0-0`.
- Internet access to pull Python wheels during build (paddleocr, paddlepaddle, pdf2image etc.).
- Paperless-ngx API token (Token Auth).

## Environment variables
- `PAPERLESS_BASE_URL` (required): e.g. `http://webserver:8000`
- `PAPERLESS_API_TOKEN` (required): Paperless API token (Authorization: Token …)
- `PAPERLESS_LANG` (optional): PaddleOCR language code, default `ch`.
- `LOG_LEVEL` (optional): logging level, default `INFO`.
- `LLM_ENABLED` (optional): `true/false`, default `false`.
- `LLM_API_BASE` (optional): OpenAI-compatible base URL, default `https://api.openai.com/v1`.
- `LLM_API_KEY` (optional): API key; required if LLM is enabled.
- `LLM_MODEL` (optional): model name, default `gpt-4.1-2025-04-14` (override if you have a faster/cheaper variant).
- `LLM_FORMAT_CONTENT` (optional): `true/false`, default `false`; when true, LLM will reformat OCR text (line breaks/spacing) without changing meaning. Complex layouts may lose fragments. Leave disabled if you only need keyword search; enable if you prioritize readability.

## Build and run (Docker)
```sh
docker run -p 8000:8000 \
  -e PAPERLESS_BASE_URL=http://webserver:8000 \
  -e PAPERLESS_API_TOKEN=YOUR_TOKEN \
  -e PAPERLESS_LANG=ch \
  fr0der1c/paperless-ocr:latest
```

## Paperless workflow setup
1. Create a workflow with trigger **Document Added**.
2. Action: **Webhook**.
3. URL: `http://<host>:8000/paperless-webhook`
4. Body: JSON including `doc_url` (or `url`), e.g.
   ```json
   {
     "doc_url": "{{doc_url}}"
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
    image: fr0der1c/paperless-ocr:latest   # or build: ./paperless-ngx-paddleocr if you prefer local build
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
- Title generation: basic fallback is first non-empty line (80 chars); enable LLM for better titles.
- If you add a second workflow with trigger **Document Updated**, add a tag or custom field filter to avoid self-trigger loops.
- The service expects Paperless API token and base URL; missing configuration will return 500/503.
- LLM: enable with `LLM_ENABLED=true`; `LLM_FORMAT_CONTENT=true` lets the LLM fix line breaks/spacing without changing meaning; failures fall back to OCR text/title.

---

# paperless-ngx companion

## 概述
Paperless-ngx 是一个优秀的自托管文档管理系统。其内置的 Tesseract OCR 识别效果有限。PaddleOCR 具有更强的识别能力，LLM 可生成更好的标题并修正OCR排版问题。本项目通过 paperless-ngx 原生的 Workflow 和 Webhook 能力，将外部 OCR 能力挂载到 Paperless-ngx，覆盖内置 OCR 的内容。

本服务是基于 FastAPI 的轻量服务，接收 Paperless-ngx Workflow Webhook（Document Added 事件），下载原文件，用 PaddleOCR 识别文本，可选用 LLM 生成标题，通过 REST API 回写 Paperless 的 `content/title` 字段。


## 功能
- `/paperless-webhook` 接收 webhook，从 `doc_url` 提取 `doc_id`。
- 下载原始文件（`/api/documents/{id}/download/?original=true`）。
- 自动区分 PDF 与图片，PDF 经 pdf2image（poppler）转图后识别。
- PaddleOCR 进程级初始化一次（语言可配置）。
- 拼接全文，可选使用 LLM 修正换行/空格后生成最终 content，取首个非空行或 LLM 生成标题（最长 80 字），PATCH 回 Paperless。
- `/healthz` 健康检查。

## 依赖环境
- Docker 基于 `python:3.10-slim`，安装 `poppler-utils`、`libgl1`、`libglib2.0-0`。
- 构建阶段需能下载 Python 依赖（paddleocr、paddlepaddle、pdf2image 等）。
- 需要 Paperless-ngx 的 API Token（Token Auth）。

## 环境变量
- `PAPERLESS_BASE_URL`（必填）：如 `http://webserver:8000`
- `PAPERLESS_API_TOKEN`（必填）：Paperless API token（Authorization: Token …）
- `PAPERLESS_LANG`（可选）：PaddleOCR 语言代码，默认 `ch`
- `LOG_LEVEL`（可选）：日志级别，默认 `INFO`
- `LLM_ENABLED`（可选）：`true/false`，默认 `false`
- `LLM_API_BASE`（可选）：OpenAI 兼容接口地址，默认 `https://api.openai.com/v1`
- `LLM_API_KEY`（可选）：大模型 API key（开启 LLM 时必填）
- `LLM_MODEL`（可选）：模型名称，默认 `gpt-4.1-2025-04-14`（可按需改更快/更便宜的）
- `LLM_FORMAT_CONTENT`（可选）：`true/false`，默认 `false`；开启后 LLM 会在保持原意的前提下纠正 OCR 文本的换行/空格，对于复杂排版有可能造成部分文字丢失。如果OCR只是为了搜索关键词，则不建议开启。如果重视内容可读性则可尝试开启。

## 构建与运行（Docker）
```sh
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
     "doc_url": "{{doc_url}}"
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
    image: fr0der1c/paperless-ocr:latest   # or build: ./paperless-ngx-paddleocr if you prefer local build
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
- LLM 生成标题：设置 `LLM_ENABLED=true`，并提供 `LLM_API_KEY`（可选改 `LLM_API_BASE` 和 `LLM_MODEL`，默认 `https://api.openai.com/v1` 与 `gpt-4.1-2025-04-14`）。失败会回退到 OCR 首行标题。
- LLM 修正排版：设置 `LLM_FORMAT_CONTENT=true`（需同时开启 `LLM_ENABLED`），仅修正换行/空格，不改语义；失败回退原 OCR 文本。
