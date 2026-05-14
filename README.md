# paperless-ngx companion

English | 中文

## Overview
This project is a lightweight FastAPI service that uses Paperless-ngx Workflow + Webhook to transparently replace the built-in OCR and metadata extraction path with a single multimodal LLM pipeline.

Once a `Document Added` webhook is configured, the service will:

1. download the original document from Paperless-ngx
2. render PDF pages to images when needed
3. run multimodal LLM OCR
4. extract `title`, `tags`, and `document_type` from the OCR result
5. PATCH the final metadata back to Paperless-ngx in one pass

The goal is "configure once, then fully automatic forever". No manual relabeling, no staged automation chain, no workflow-control tags.

## Why This Project Exists
Paperless-ngx is an excellent self-hosted DMS, but its built-in OCR and downstream metadata enrichment may not be enough if you want a fully LLM-driven pipeline.

This project is designed for a different goal than generic AI add-ons:

- use multimodal LLMs for OCR itself, not just post-processing
- complete OCR and metadata extraction in one webhook-driven pass
- update Paperless-ngx automatically without user intervention
- avoid polluting the tag system with workflow-state labels
- behave like a transparent external replacement for the built-in capability

## Why Not `paperless-gpt`
`paperless-gpt` is not aimed at this "single webhook, fully automatic, transparent replacement" workflow.

For this use case, the main problems are:

- it typically depends on custom tags as control signals, so users or automations must keep moving documents through stages manually
- it does not provide a single built-in path that completes OCR plus title/tag/document-type extraction in one pass
- if you try to chain multiple Paperless automations together to simulate this flow, document updates can retrigger later steps and easily lead to infinite loops

This project takes the opposite approach:

- only one webhook trigger is needed
- OCR, title extraction, tag selection, and document type selection happen in one request
- the service updates Paperless-ngx once with the final result
- tags are treated as business metadata only, never as workflow-state markers

## Feature Summary
- Receive webhook at `POST /paperless-webhook`
- Extract `doc_id` from `doc_url` or `url`
- Download original file from `/api/documents/{id}/download/?original=true`
- Auto-detect PDF vs image and convert PDFs with `pdf2image`
- Run multimodal LLM OCR through an OpenAI-compatible API
- Extract `title`, `tags`, and `document_type` from OCR text
- Only choose from existing Paperless tags and existing document types
- Single PATCH back to Paperless-ngx
- Health check at `GET /healthz`

## Important Behavior
- `tags` are never auto-created
- `document_type` is never auto-created
- the model is only allowed to choose from the existing tag/type lists fetched from Paperless-ngx
- if no suitable tag exists, the model must return `[]`
- if no suitable document type exists, the model must return `null`
- no workflow-control tags such as `ocr-done`, `needs-tagging`, or similar are introduced

## Requirements
- Python 3.10+
- `poppler-utils` for PDF to image conversion
- a Paperless-ngx API token
- an OpenAI-compatible API endpoint for chat completions
- the OCR endpoint must support multimodal / vision input via `image_url`
- `uv` for local dependency management and lockfile-driven installs

## Dependency Management
This project uses `pyproject.toml` + `uv.lock` as the single source of truth for Python dependencies.

- edit dependencies in `pyproject.toml`
- refresh the lockfile with `uv lock`
- install locally with `uv sync --locked`
- Docker builds also install from `uv.lock`

`requirements.txt` is intentionally not used, to avoid manual drift between multiple dependency manifests.

## Environment Variables
### Required
- `PAPERLESS_BASE_URL`: for example `http://webserver:8000`
- `PAPERLESS_API_TOKEN`: Paperless-ngx API token
- `LLM_API_KEY`: default API key for OpenAI-compatible calls

### General LLM Defaults
- `LLM_API_BASE`: default OpenAI-compatible base URL, default `https://api.openai.com/v1`
- `LLM_MODEL`: default model name, default `gpt-5.5`

### OCR-Specific Overrides
- `LLM_OCR_API_BASE`: optional dedicated OCR base URL
- `LLM_OCR_API_KEY`: optional dedicated OCR API key
- `LLM_OCR_MODEL`: optional dedicated OCR model
- `LLM_OCR_MAX_TOKENS`: default `4096`
- `LLM_OCR_IMAGE_MAX_SIZE`: default `2048`
- `LLM_OCR_IMAGE_DETAIL`: default `high`

### Extraction-Specific Overrides
- `LLM_EXTRACT_API_BASE`: optional dedicated extraction base URL
- `LLM_EXTRACT_API_KEY`: optional dedicated extraction API key
- `LLM_EXTRACT_MODEL`: optional dedicated extraction model
- `LLM_EXTRACT_INPUT_CHAR_LIMIT`: default `12000`
- `LLM_EXTRACT_MAX_TOKENS`: default `1200`

### Runtime Controls
- `LOG_LEVEL`: default `INFO`
- `REQUEST_TIMEOUT`: default `30`
- `LLM_REQUEST_TIMEOUT`: default `120`
- `LLM_PAGE_CONCURRENCY`: default `2`
- `LLM_MAX_PAGES`: default `20`
- `PAPERLESS_PAGE_SIZE`: default `1000`

## Build and Run
### Local
```sh
uv sync --locked
uv run uvicorn app:app --host 0.0.0.0 --port 8000
```

### Docker
```sh
docker build -t paperless-ngx-companion .

docker run -p 8000:8000 \
  -e PAPERLESS_BASE_URL=http://webserver:8000 \
  -e PAPERLESS_API_TOKEN=YOUR_TOKEN \
  -e LLM_API_BASE=https://api.openai.com/v1 \
  -e LLM_API_KEY=YOUR_LLM_KEY \
  -e LLM_MODEL=gpt-5.5 \
  paperless-ngx-companion
```

### Example with Separate OCR and Extraction Models
```sh
docker run -p 8000:8000 \
  -e PAPERLESS_BASE_URL=http://webserver:8000 \
  -e PAPERLESS_API_TOKEN=YOUR_TOKEN \
  -e LLM_API_KEY=DEFAULT_KEY \
  -e LLM_OCR_API_BASE=https://your-vision-endpoint/v1 \
  -e LLM_OCR_MODEL=gpt-4.1 \
  -e LLM_EXTRACT_API_BASE=https://your-text-endpoint/v1 \
  -e LLM_EXTRACT_MODEL=gpt-4.1-mini \
  paperless-ngx-companion
```

## Paperless Workflow Setup
1. Create a workflow with trigger **Document Added**
2. Add action **Webhook**
3. Set URL to `http://<host>:8000/paperless-webhook`
4. Use JSON body:

```json
{
  "doc_url": "{{doc_url}}"
}
```

After that, every newly added document will go through the external LLM OCR pipeline automatically.

## Docker Compose Example
```yaml
services:
  ocr-service:
    build: .
    environment:
      PAPERLESS_BASE_URL: http://webserver:8000
      PAPERLESS_API_TOKEN: ${PAPERLESS_API_TOKEN}
      LLM_API_BASE: ${LLM_API_BASE}
      LLM_API_KEY: ${LLM_API_KEY}
      LLM_MODEL: ${LLM_MODEL}
      LLM_OCR_MODEL: ${LLM_OCR_MODEL}
      LLM_EXTRACT_MODEL: ${LLM_EXTRACT_MODEL}
    depends_on:
      - webserver
    restart: unless-stopped
    networks:
      - paperless

networks:
  paperless:
    external: true
```

## Local OCR Debugging
You can test OCR locally against an image or PDF:

```sh
uv run python local_ocr_test.py /path/to/file.pdf
```

The script uses the same LLM OCR path as the webhook service.

## Notes
- The service only supports OpenAI-compatible APIs
- For OCR, the endpoint must support multimodal input with `image_url`
- Metadata extraction is best-effort; if extraction fails, OCR content is still written back
- Title falls back to the first non-empty OCR line if extraction does not return a usable title
- Tags are appended conservatively by merging with the document's existing tags
- If no suitable existing tag or document type is found, the corresponding field is skipped

---

# paperless-ngx companion

## 概述
这是一个基于 FastAPI 的轻量服务，通过 Paperless-ngx 的 Workflow + Webhook，把文档处理链路改造成“纯 LLM、多模态 OCR、一次性元数据抽取并回写”的模式。

当你配置好 `Document Added -> Webhook` 之后，服务会自动完成：

1. 从 Paperless-ngx 下载原始文档
2. 如果是 PDF，则转成图片页
3. 使用多模态大模型执行 OCR
4. 基于 OCR 文本抽取 `title`、`tags`、`document_type`
5. 一次性 PATCH 回写到 Paperless-ngx

目标是：**配置一次，然后完全自动化运行**。不依赖人工改标签，不依赖多段自动化链式推进，也不引入流程控制标签。

## 为什么会有这个项目
Paperless-ngx 本身已经很好用，但如果你想要的是：

- OCR 本身就由多模态 LLM 完成
- OCR、标题、标签、分类在一次处理里完成
- 用户只配置一次 webhook，后面完全自动化
- 对使用者来说像是“透明替换了 Paperless 的内部能力”

那么单纯在后处理阶段接一点 AI 能力还不够。

这个项目的目标不是给 Paperless 再套一层复杂 AI 工作流，而是把整个 OCR 与元数据更新过程收敛成一个 webhook 闭环。

## 为什么不是 `paperless-gpt`
`paperless-gpt` 并不是为这个“单 webhook、完全自动、透明替换式”的场景设计的。

在这个场景下，它的几个问题比较明显：

- 它依赖自定义标签来推进处理阶段，通常需要用户手动打标，或者让自动化反复改标签
- 它不适合在一次流程里同时完成 OCR、标题提取、标签提取、分类提取并最终回写
- 如果试图通过 Paperless 的自动化链式串联这些步骤，文档更新很容易再次触发后续动作，最终形成无限循环

本项目采用完全相反的思路：

- 只需要一个 webhook 触发
- OCR、标题抽取、标签选择、分类选择都在一次请求里完成
- 最后只对 Paperless-ngx 做一次最终更新
- 标签只表示文档语义，不承担流程状态控制作用

## 功能摘要
- `POST /paperless-webhook` 接收 webhook
- 从 `doc_url` 或 `url` 中提取 `doc_id`
- 下载 `/api/documents/{id}/download/?original=true`
- 自动识别 PDF / 图片，PDF 使用 `pdf2image` 转图
- 通过 OpenAI-compatible 接口执行多模态 LLM OCR
- 基于 OCR 文本抽取 `title`、`tags`、`document_type`
- 标签和分类都只会从 Paperless 已有项目中选择
- 一次性 PATCH 回写到 Paperless-ngx
- `GET /healthz` 健康检查

## 关键行为约束
- **绝不自动创建标签**
- **绝不自动创建 document type**
- 模型只能从 Paperless 当前已有标签列表中选择标签
- 如果没有合适标签，必须返回 `[]`
- 模型只能从当前已有 document type 列表中选择分类
- 如果没有合适分类，必须返回 `null`
- 不引入任何流程驱动标签，例如 `ocr-done`、`needs-tagging`

## 依赖要求
- Python 3.10+
- `poppler-utils`，用于 PDF 转图片
- Paperless-ngx API Token
- 一个 OpenAI-compatible 的聊天补全接口
- OCR 所使用的接口必须支持多模态 / 视觉输入，也就是支持 `image_url`
- 本地依赖管理使用 `uv`

## 依赖管理
本项目以 `pyproject.toml + uv.lock` 作为 Python 依赖的唯一真相来源。

- 修改依赖时只改 `pyproject.toml`
- 用 `uv lock` 更新锁文件
- 本地通过 `uv sync --locked` 安装
- Docker 构建也直接基于 `uv.lock` 安装

项目里不再使用 `requirements.txt`，避免出现多份依赖声明手动同步而导致漂移。

## 环境变量
### 必填
- `PAPERLESS_BASE_URL`：例如 `http://webserver:8000`
- `PAPERLESS_API_TOKEN`：Paperless-ngx API Token
- `LLM_API_KEY`：默认的大模型 API Key

### 全局默认模型配置
- `LLM_API_BASE`：默认 OpenAI-compatible Base URL，默认 `https://api.openai.com/v1`
- `LLM_MODEL`：默认模型名，默认 `gpt-5.5`

### OCR 专用覆盖配置
- `LLM_OCR_API_BASE`：可选，OCR 专用 Base URL
- `LLM_OCR_API_KEY`：可选，OCR 专用 API Key
- `LLM_OCR_MODEL`：可选，OCR 专用模型
- `LLM_OCR_MAX_TOKENS`：默认 `4096`
- `LLM_OCR_IMAGE_MAX_SIZE`：默认 `2048`
- `LLM_OCR_IMAGE_DETAIL`：默认 `high`

### 抽取专用覆盖配置
- `LLM_EXTRACT_API_BASE`：可选，抽取专用 Base URL
- `LLM_EXTRACT_API_KEY`：可选，抽取专用 API Key
- `LLM_EXTRACT_MODEL`：可选，抽取专用模型
- `LLM_EXTRACT_INPUT_CHAR_LIMIT`：默认 `12000`
- `LLM_EXTRACT_MAX_TOKENS`：默认 `1200`

### 运行控制
- `LOG_LEVEL`：默认 `INFO`
- `REQUEST_TIMEOUT`：默认 `30`
- `LLM_REQUEST_TIMEOUT`：默认 `120`
- `LLM_PAGE_CONCURRENCY`：默认 `2`
- `LLM_MAX_PAGES`：默认 `20`
- `PAPERLESS_PAGE_SIZE`：默认 `1000`

## 构建与运行
### 本地
```sh
uv sync --locked
uv run uvicorn app:app --host 0.0.0.0 --port 8000
```

### Docker
```sh
docker build -t paperless-ngx-companion .

docker run -p 8000:8000 \
  -e PAPERLESS_BASE_URL=http://webserver:8000 \
  -e PAPERLESS_API_TOKEN=YOUR_TOKEN \
  -e LLM_API_BASE=https://api.openai.com/v1 \
  -e LLM_API_KEY=YOUR_LLM_KEY \
  -e LLM_MODEL=gpt-5.5 \
  paperless-ngx-companion
```

### 使用不同 OCR / 抽取模型的示例
```sh
docker run -p 8000:8000 \
  -e PAPERLESS_BASE_URL=http://webserver:8000 \
  -e PAPERLESS_API_TOKEN=YOUR_TOKEN \
  -e LLM_API_KEY=DEFAULT_KEY \
  -e LLM_OCR_API_BASE=https://your-vision-endpoint/v1 \
  -e LLM_OCR_MODEL=gpt-4.1 \
  -e LLM_EXTRACT_API_BASE=https://your-text-endpoint/v1 \
  -e LLM_EXTRACT_MODEL=gpt-4.1-mini \
  paperless-ngx-companion
```

## Paperless 工作流配置
1. 新建 Workflow，触发器选择 **Document Added**
2. 添加动作 **Webhook**
3. URL 填写 `http://<host>:8000/paperless-webhook`
4. Body 选择 JSON，内容如下：

```json
{
  "doc_url": "{{doc_url}}"
}
```

配置完成后，新文档会自动进入外部 LLM OCR 流程。

## Docker Compose 示例
```yaml
services:
  ocr-service:
    build: .
    environment:
      PAPERLESS_BASE_URL: http://webserver:8000
      PAPERLESS_API_TOKEN: ${PAPERLESS_API_TOKEN}
      LLM_API_BASE: ${LLM_API_BASE}
      LLM_API_KEY: ${LLM_API_KEY}
      LLM_MODEL: ${LLM_MODEL}
      LLM_OCR_MODEL: ${LLM_OCR_MODEL}
      LLM_EXTRACT_MODEL: ${LLM_EXTRACT_MODEL}
    depends_on:
      - webserver
    restart: unless-stopped
    networks:
      - paperless

networks:
  paperless:
    external: true
```

## 本地 OCR 调试
可以直接对本地图片或 PDF 跑同一套 LLM OCR 流程：

```sh
uv run python local_ocr_test.py /path/to/file.pdf
```

## 说明
- 本项目只兼容 OpenAI-compatible 接口
- OCR 所用接口必须支持 `image_url` 形式的多模态输入
- 元数据抽取是 best-effort；即使抽取失败，也会尽量把 OCR 文本回写
- `title` 提取失败时，会回退到 OCR 的第一条非空文本
- 标签采用保守并集策略：保留文档原有标签，再附加本次成功匹配到的已有标签
- 如果不存在合适的已有标签或已有分类，则对应字段跳过更新
