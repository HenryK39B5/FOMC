# 宏观事件月报（DDGS + LLM + SQLite）

按月收集高信号宏观新闻（DDGS），用 LLM 甄别并摘要事件，生成月度报告，支持 Web/CLI/代码调用。

## 快速开始
- 安装依赖：`pip install -r requirements.txt`（ddgs, fastapi, uvicorn, python-dateutil, requests, openai, python-dotenv, bs4, markdown2）
- 环境变量（`.env`）：`DEEPSEEK_API_KEY`（必填），可选 `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`
- 运行 Web：`uvicorn webapp:app --reload --port 8000`，浏览 `http://localhost:8000`，输入 `YYYY-MM`，点击 Fetch/Refresh，查看事件时间线与月报（Markdown，带来源胶囊）
- CLI 示例：`python manage_db.py refresh-month --month-key 2024-08 --force`
  - 查看：`python manage_db.py list-months` / `list-events --month-key 2024-08`
  - 导出：`python manage_db.py export-month --month-key 2024-08`
  - 删除：`python manage_db.py delete-month --month-key 2024-08`
  - 重置状态：`python manage_db.py reset-status --month-key 2024-08`
  - 清空全部：`python manage_db.py clear-all`
  - 手动全清（含原文表）：
    ```bash
    python - <<'PY'
    import sqlite3
    conn=sqlite3.connect('data/macro_events.db')
    conn.execute('DELETE FROM events;')
    conn.execute('DELETE FROM months;')
    conn.execute('DELETE FROM raw_articles;')
    conn.commit(); conn.close(); print('events/months/raw_articles cleared')
    PY
    ```
- 代码调用：
  ```python
  from macro_events.report_entrypoints import get_events_for_month
  events = get_events_for_month(2024, 8)  # 写入 data/macro_events.db
  ```

## 数据流与 LLM 角色
1) 多轮搜索：DDGS `news()`，关键词覆盖劳资/关税制裁/工业政策/供应链/能源/金融稳定/地缘冲突/公共卫生/全局冲击；每轮附月份提示。
2) LLM 选重要链接：PRIMARY（抓正文）/ SUPP（摘要），并存入 `raw_articles`。
3) 规则标签：时间过滤、URL 去重、冲击类型/影响通道/国家猜测（纯规则，不用 LLM）。
4) 聚类成事件：按 (date, shock_type) 聚合，重要性=来源数+优质域名加权，自适应筛选（cap 20）。
5) 事件摘要与排序（LLM）：对事件生成 2-3 句中文摘要并按宏观重要性重排/筛选（约 5–12 条）。
6) 月报撰写（LLM）：Markdown 分段（通胀/就业/增长/金融稳定/供应链/地缘等），段尾来源胶囊；存入 `months.monthly_summary`。

## 存储
- SQLite：`months`（状态、payload、monthly_summary）、`events`（事件+source_meta）、`raw_articles`（snippet/full_text/domain）。文件位于 `data/macro_events.db`（已 gitignore）。

## UI 概览
- 事件页：时间线 + 玻璃卡片；事件包含日期/标签/Score/LLM 摘要，PRIMARY 展示正文，SUPP 展示摘要，来源卡片 hover 浮起；顶部按钮跳转月报。
- 月报页：窄列阅读卡，Markdown 渲染，来源行自动转成链接胶囊。

## 注意
- LLM 必须配置（未设置 `DEEPSEEK_API_KEY` 会报错）；流程默认开启 LLM。
- DDGS 不返回全文，PRIMARY 链接才抓取正文；SUPP 仅存摘要片段。
