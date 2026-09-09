# IT 知识助手 PoC

当前提供本地网页聊天、文档自动导入和可配置内网模型问答。现有 Hermes 手册已通过通用导入器建立知识库。

## 启动与操作

```powershell
cd "D:\浩鲸科技\it机器人"
.\.venv\Scripts\python.exe -X utf8 -m streamlit run app/streamlit_app.py
```

浏览器打开 http://127.0.0.1:8501 。也可以在项目根目录运行 start_chat.ps1。终端 Ctrl+C 停止前台服务。

1. 在“知识库”页签选择一份或多份 Word（.docx）、文字版 PDF、TXT、Markdown。
2. 点击“导入所选文件”。正文解析、章节拆分及索引更新都在本机完成，不调用模型。
3. 检查导入结果和警告，在“已导入资料”展开预览正文及来源。
4. 切换“提问”。“模型问答”会结合近期会话理解问题，依据检索文档回答、追问或拒答。
5. “原文检索”可以不联网测试，仅返回匹配内容，不判断是否能回答问题。
6. “新对话”清空历史；调试模式展示查询改写、排名、引用证据及耗时。

同内容重复导入会跳过；同名新内容替换旧版；“从知识库移除”会删除当前索引中的对应内容。发布新版本成功后页面清空旧会话，避免引用已经撤下的文档。历史索引快照仍在本机 artifacts/library 中保留，不再参与查询；移除并非物理擦除历史文件。

## 模型配置和当前连接情况

在本机 .env 中设置以下字段，进程环境变量优先：

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=<公司提供的接口地址，以 /v1 结尾>
LLM_MODEL=<模型名称>
LLM_API_KEY=<本机填写，勿提交>
```

也接受完整 /chat/completions 地址。页面“测试模型连接”只发送一句问候，不发送手册。

本次实际连接测试遇到 DNS 解析失败（11001）：电脑无法解析已配置的模型域名，请连接公司网络/VPN，必要时联系接口管理员核对 DNS。无需重写代码；网络恢复后点击测试连接即可。不得关闭 TLS 验证绕过网络问题。接口权限、真实结构化输出兼容性和实际问答质量仍需连通后验证；没有用 Mock 冒充真实模型效果。

网络、认证、超时或返回格式错误会显示 ERROR，不会回退到原文并假装是模型回答，也不会算作 NO_ANSWER。

## 自动导入做了什么

- python-docx 按正文顺序读取段落和表格，利用标题样式或大纲级别分组。Word 引用到章节和正文块，不猜页码。
- pypdf 提取文字版 PDF，保留真实 PDF 页号；扫描/空白页列入警告。PDF 表格和多栏阅读顺序需要预览核对。
- TXT/Markdown 按行提取，Markdown 标题作为章节；优先 UTF-8，兼容 GB18030。
- 每片约 1800 字符。保留全部正文；过长段落/表格拆分并告警，不静默截断。不强行把手册编造成 FAQ 问答。
- 明确标注的 API Key、AppSecret 等凭据和内网 IP URL 会替换为占位符。这是基本规则，不是完整敏感信息识别器；导入前仍需使用允许处理的资料。
- 限制每文件 20 MB、正文 50 万字符、PDF 300 页、DOCX 解压后 100 MB。暂不支持 .doc、加密 PDF、OCR、图像、复杂版面或文本框内容解析。
- 内容哈希用于重复检测；索引构建完成后原子切换活动版本。单个文件失败保留旧索引，批量其他文件继续处理。
- 上传原始字节仅用于解析，不单独保存原文件；保留解析片段和导入记录。原始手册请自行保留。

## 问答流程和接口

`src/llm/base.py` 提供 LLMProvider.chat / structured_output，`src/llm/internal.py` 实现 OpenAI 风格接口。地址和密钥不写死，不自动访问其他 Provider，不记录请求正文、原始响应或密钥。JSON 输出通过 Pydantic 校验，格式错误最多修正一次。

`src/query_understanding.py` 将当前问题及最多 8 条近期消息解释为独立查询；只有关键条件缺失才澄清，模型负责区分“怎么启动”和“启动失败”。

`src/qa_pipeline.py` 调用现有 BM25 Top10；最多提供 20000 字符的完整候选文档上下文。`src/answer_generator.py` 要求每条回答带文档 ID 和原文证据，程序验证 ID 及引用原文确实存在。校验失败修正一次，仍失败显示 ERROR。证据不足返回固定 NO_ANSWER；来源由程序回填。

引用存在并不能数学上保证生成内容忠实，因此还需要人工审核真实回答。提示词要求文档中的角色设定/指令只能作为资料，不得覆盖系统规则。当前无向量检索、RRF、Reranker；仅增加模型理解和基于证据的生成，BM25 仍可能漏召回。

`src/document_import.py` 负责自动解析；`src/library.py` 保存不可变版本及活动指针；`app/streamlit_app.py` 负责上传、预览、删除和聊天。输入为文件/问题，输出为带来源的文档片段/模型回答及状态。无需增加 HTTP 服务或大型 RAG 框架。

## 测试和复现

新机器先安装锁定依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

测试涵盖 Word 标题/表格、PDF 正文/空白页、长文本完整性、基本脱敏、文件去重/更新/删除、构建失败回滚、路径隔离、引用 ID/原文校验、澄清不检索、连续问题上下文、HTTP 错误脱敏，以及网页连续提问和清空会话。模型测试用明确的模拟响应，不访问真实接口。

原始阶段一命令仍可用：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m src.ingest
.\.venv\Scripts\python.exe -X utf8 -m src.pipeline --query "如何启动 Hermes Agent" --top-k 1
.\.venv\Scripts\python.exe -X utf8 -m src.evaluation --modes bm25
```

这些 CLI 使用 config.yaml 指定的静态 FAQ 数据，独立于页面上传知识库。旧演示数据和 Hermes 一次性导入数据保留；旧自动生成测试题仅验证链路，不能作为业务质量指标。页面数据位于 artifacts/library，重启后仍可读取，不必重复上传。

## 安全与限制

本地监听 127.0.0.1，Streamlit 遥测关闭。聊天只保存在会话内存。原文检索与导入不联网；仅在模型问答或测试连接时请求明确配置的模型接口。模型问答会发送近期会话和检索片段，应使用公司允许处理的知识资料。

.env、env.txt、artifacts 和 reports 已忽略版本控制。索引、历史快照和原始手册仍属于内部数据，须按其敏感级别保管。不会执行手册里的命令，不修改账号，不访问 AD，不自动提工单。

开源依赖参考：BM25S（https://github.com/xhluca/bm25s）、python-docx（https://python-docx.readthedocs.io/）、pypdf（https://pypdf.readthedocs.io/）、Streamlit（https://docs.streamlit.io/）。
