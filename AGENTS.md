# AGENTS

## 项目定位
- 这是一个通过 `Workflow + Webhook` 透明替换 Paperless-ngx 内置 OCR/元数据提取能力的服务。
- 主链路是：下载文档 -> PDF 转图 -> 多模态 LLM OCR -> 抽取标题/标签/分类 -> 单次回写 Paperless-ngx。
- 保持“配置一次 webhook 后全自动运行”的产品方向，避免引入需要人工推进的流程设计。

## 产品约束
- 只支持 OpenAI-compatible 接口。
- OCR 使用的接口必须支持图片输入。
- `tags` 只能从 Paperless-ngx 现有标签中选择，绝不自动创建新标签。
- `document_type` 只能从现有类型中选择，绝不自动创建新类型。
- 不引入流程驱动标签，例如 `ocr-done`、`needs-tagging`。
- 目前不做 `correspondent` 和 `custom_fields`。

## 模型与配置
- 默认模型是 `gpt-5.5`。
- 允许 OCR 与抽取分别使用不同的 `API_BASE` / `API_KEY` / `MODEL`。
- `*_API_BASE` 应按完整 OpenAI-compatible Base URL 处理；对于 OpenAI 官方接口，必须包含 `/v1`，不能省略。代码内部会统一去掉末尾斜杠。
- 未显式设置 `LLM_OCR_*` 或 `LLM_EXTRACT_*` 时，回退到全局 `LLM_*`。

## 依赖管理
- 依赖的唯一真相来源是 `pyproject.toml + uv.lock`。
- 不再维护 `requirements.txt`。
- 修改依赖时先改 `pyproject.toml`，再运行 `uv lock` 更新锁文件。

## Docker 约定
- Docker 构建应优先利用缓存：先复制 `pyproject.toml` 和 `uv.lock`，先安装依赖，再复制项目源码。
- 依赖安装使用 `uv sync --locked --no-dev --no-install-project`。
- 保留 `poppler-utils`，因为当前仍通过 `pdf2image` 支持 PDF 转图。

## 文档边界
- `README.md` 面向项目使用者，不要堆放只对 coding agent 有意义的内部约束。
- README 优先回答三件事：为什么有这个项目、它是干嘛的、如何接入现有的 Paperless-ngx 与如何运行。
- 面向 agent 的长期规则、实现边界和维护约定，优先写在 `AGENTS.md`。
