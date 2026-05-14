# paperless-ngx companion

[English](#paperless-ngx-companion) | [中文](#paperless-ngx-companion-1)

## What is this
`paperless-ngx companion` is a small FastAPI service that uses Paperless-ngx Workflow + Webhook to transparently replace the built-in OCR flow with a multimodal LLM pipeline.

After you configure one `Document Added -> Webhook`, every new document can be processed automatically:

1. download the original file from Paperless-ngx
2. convert PDF pages to images when needed
3. run multimodal LLM OCR
4. extract title, tags, and document type from the OCR text
5. write the final metadata back to Paperless-ngx

The goal is simple: make Paperless-ngx feel like it has a better built-in OCR and metadata extraction pipeline, without requiring users to manually push documents through extra stages.

## Why this project exists
I wanted a workflow that is fully automatic after a single webhook is configured.

That means:

- OCR itself should be handled by a multimodal LLM
- OCR, title extraction, tag selection, and document type selection should finish in one pass
- documents should not need to be moved forward by manually changing tags
- the tag system should keep representing document meaning, not workflow state

## Why not `paperless-gpt`
`paperless-gpt` solves a different problem.

For this project, the issue is not "add some AI somewhere", but "complete OCR and metadata extraction in one fully automatic pass". In practice, `paperless-gpt` depends on its own tagging workflow, and users often need to keep changing tags manually to move documents through stages. If you try to force the same behavior through Paperless automation, document updates can retrigger later steps and easily create infinite loops.

This project avoids that by doing everything in one webhook request and then updating Paperless-ngx once with the final result.

## Installation

Add this service to your existing Paperless-ngx docker-compose file:

```yaml
services:
  ocr-service:
    image: fr0der1c/paperless-ocr:latest
    environment:
      PAPERLESS_BASE_URL: http://webserver:8000
      PAPERLESS_API_TOKEN: ${PAPERLESS_API_TOKEN}
      LLM_API_BASE: ${LLM_API_BASE:-https://api.openai.com/v1}
      LLM_API_KEY: ${LLM_API_KEY}
      LLM_MODEL: ${LLM_MODEL:-gpt-5.5}
    depends_on:
      - webserver
    restart: unless-stopped
```

You need to replace `PAPERLESS_API_TOKEN` and `LLM_API_KEY` with your actual values.

Then create a workflow in Paperless-ngx:

1. Trigger: **Document Added**
2. Action: **Webhook**
3. URL: `http://ocr-service:8000/paperless-webhook`
4. Do not enable `Use parameters as webhook payload`
5. Enable `Send webhook payload as JSON`
6. Set the webhook payload to:

```json
{
  "doc_url": "{{ doc_url }}"
}
```

7. Turn off `Add document`.

`{{ doc_url }}` requires `PAPERLESS_URL` to be configured in Paperless-ngx.

After that, newly added documents will go through the external OCR pipeline automatically.

If you want OCR and metadata extraction to use different model endpoints, you can add these optional variables:

| Variable | Example | Notes |
| --- | --- | --- |
| `LLM_OCR_API_BASE` | `https://api.openai.com/v1` | Use the full OpenAI-compatible base URL. For the official OpenAI API, `/v1` is required and must not be omitted. A trailing slash is fine; the service trims it automatically. |
| `LLM_OCR_API_KEY` | `sk-xxx` | OCR-specific API key. Leave it unset to fall back to `LLM_API_KEY`. |
| `LLM_OCR_MODEL` | `gpt-5.5` | OCR-specific model. Leave it unset to fall back to `LLM_MODEL`. |
| `LLM_EXTRACT_API_BASE` | `https://api.openai.com/v1` | Same rule as above. For the official OpenAI API, `/v1` is required and must not be omitted. |
| `LLM_EXTRACT_API_KEY` | `sk-xxx` | Extraction-specific API key. Leave it unset to fall back to `LLM_API_KEY`. |
| `LLM_EXTRACT_MODEL` | `gpt-5.5` | Extraction-specific model. Leave it unset to fall back to `LLM_MODEL`. |

The service expects an OpenAI-compatible API, and the OCR endpoint must support image input.

## Run locally
If you are not using Docker and want to run the service locally:

```sh
uv sync --locked
uv run uvicorn app:app --host 0.0.0.0 --port 8000
```

The project uses `pyproject.toml + uv.lock` as the single source of truth for dependencies.

## Local OCR debugging
If you want to debug OCR locally against an image or PDF:

```sh
uv run python local_ocr_test.py /path/to/file.pdf
```

---

# paperless-ngx companion

## 这是什么
`paperless-ngx companion` 是一个很小的 FastAPI 服务。它通过 Paperless-ngx 的 Workflow + Webhook，把内置 OCR 流程透明地替换成“多模态大模型 OCR + 元数据抽取”的外部处理链路。

你只需要配置一次 `Document Added -> Webhook`，之后每个新文档都会自动完成：

1. 从 Paperless-ngx 下载原始文件
2. 如果是 PDF，就先转成图片页
3. 使用多模态大模型做 OCR
4. 基于 OCR 文本提取标题、标签和分类
5. 把最终结果回写到 Paperless-ngx

这个项目想解决的核心问题很简单：让 Paperless-ngx 看起来像是“自带了更好的 OCR 和元数据提取能力”，而不是让用户再维护一套额外的手工流程。

## 为什么会有这个项目
我想要的是一种在配置一次 webhook 之后就能完全自动运行的处理方式。

也就是说：

- OCR 本身由多模态大模型完成
- OCR、标题提取、标签选择、分类选择在一次处理中结束
- 用户不需要再靠手动改标签去推动文档流转
- 标签体系本身仍然只表达文档语义，而不是流程状态

## 为什么不是 `paperless-gpt`
`paperless-gpt` 解决的是另一类问题。

这个项目关心的不是“给 Paperless 随便加一点 AI”，而是“在一次完全自动的流程里完成 OCR 和元数据提取”。在实际使用里，`paperless-gpt` 更依赖它自己的标签推进方式，用户往往需要不断手动改标签来推动文档进入下一阶段。如果试图用 Paperless 自动化去强行串起同样的行为，文档更新又会反过来触发后续步骤，最后很容易形成无限循环。

这个项目的做法更直接：在一次 webhook 请求里完成所有处理，然后只对 Paperless-ngx 做一次最终更新。

## 安装

把这个服务加到你现有的 Paperless-ngx docker-compose 里：

```yaml
services:
  ocr-service:
    image: fr0der1c/paperless-ocr:latest
    environment:
      PAPERLESS_BASE_URL: http://webserver:8000
      PAPERLESS_API_TOKEN: ${PAPERLESS_API_TOKEN}
      LLM_API_BASE: ${LLM_API_BASE:-https://api.openai.com/v1}
      LLM_API_KEY: ${LLM_API_KEY}
      LLM_MODEL: ${LLM_MODEL:-gpt-5.5}
    depends_on:
      - webserver
    restart: unless-stopped

```

你需要将 PAPERLESS_API_TOKEN、LLM_API_KEY 替换为实际值。

然后在 Paperless-ngx 里新建一个 Workflow：

1. Trigger: **Document Added**
2. Action: **Webhook**
3. URL: `http://ocr-service:8000/paperless-webhook`
4. 不要打开 `使用参数作为 webhook 负载`
5. 打开 `以 JSON 格式发送网络钩子的有效负载`
6. 将 webhook payload 设置为：

```json
{
  "doc_url": "{{ doc_url }}"
}
```

7. 关闭 `添加文档`。

`{{ doc_url }}` 依赖 Paperless-ngx 的 `PAPERLESS_URL` 配置。

如果你希望 OCR 和后续抽取分别使用不同的模型接口，还可以额外配置：

| 变量 | 示例值 | 说明 |
| --- | --- | --- |
| `LLM_OCR_API_BASE` | `https://api.openai.com/v1` | 填完整的 OpenAI-compatible Base URL。对于 OpenAI 官方接口，`/v1` 是必需的，不能省略。末尾是否带斜杠都可以，服务内部会自动去掉。 |
| `LLM_OCR_API_KEY` | `sk-xxx` | OCR 专用 API Key。不填时会回退到 `LLM_API_KEY`。 |
| `LLM_OCR_MODEL` | `gpt-5.5` | OCR 专用模型名。不填时会回退到 `LLM_MODEL`。 |
| `LLM_EXTRACT_API_BASE` | `https://api.openai.com/v1` | 规则同上。对于 OpenAI 官方接口，`/v1` 是必需的，不能省略。 |
| `LLM_EXTRACT_API_KEY` | `sk-xxx` | 抽取专用 API Key。不填时会回退到 `LLM_API_KEY`。 |
| `LLM_EXTRACT_MODEL` | `gpt-5.5` | 抽取专用模型名。不填时会回退到 `LLM_MODEL`。 |

服务要求对接的是 OpenAI-compatible 接口，并且 OCR 所使用的接口必须支持图片输入。

## 本地运行
如果你不是要把它塞进 Docker，而是想直接在本地跑服务：

```sh
uv sync --locked
uv run uvicorn app:app --host 0.0.0.0 --port 8000
```

项目依赖以 `pyproject.toml + uv.lock` 为准。

## 本地调试 OCR
```sh
uv run python local_ocr_test.py /path/to/file.pdf
```
