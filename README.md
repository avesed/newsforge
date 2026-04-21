# NewsForge

新闻聚合与智能分析平台。从 RSS、API、网页抓取等多种来源采集新闻，经 LLM 驱动的处理管线自动分类、评分、摘要、翻译，通过 Web 前端和 API 对外服务。

## 功能亮点

- **多源采集** — 原生 RSS、RSSHub、Finnhub、Google News 等，统一适配器接口，易于扩展
- **LLM 智能管线** — 自动去重 → 语言检测 → 分类 → 按类别路由到不同深度的处理流程（评分、全文抓取、深度分析、情感/实体提取、翻译）
- **10 大分类** — finance / tech / politics / entertainment / gaming / sports / world / science / health / other，每个分类的处理深度可独立配置
- **PWA 友好** — 响应式前端，iOS standalone 模式适配，下拉刷新，中英双语切换
- **API 服务** — RESTful API 供外部系统消费（如 [WebStock](https://github.com/Avesed/webstock) 对接），支持 JWT 用户认证和 X-API-Key 机器认证
- **向量搜索** — 基于 pgvector 的语义检索

## 技术栈

| 层面 | 技术 |
|------|------|
| 后端 | Python 3.11 · FastAPI · SQLAlchemy 2 (async) · APScheduler |
| 前端 | React 18 · TypeScript · Vite · Tailwind CSS · Zustand · React Query |
| 数据库 | PostgreSQL 16 + pgvector · Redis 7 |
| LLM | OpenAI (默认 gpt-4o-mini) · 可切换 Anthropic |
| 内容抓取 | Crawl4AI · Playwright · Tavily |
| NLP | SimHash + MinHash 去重 · Lingua 语言检测 |
| 部署 | Docker (multi-stage) · Nginx · Supervisord |

## 快速开始

### 环境要求

- Docker & Docker Compose
- （可选）本地开发需 Python 3.11+、Node.js 20+

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填入：
- `OPENAI_API_KEY` — LLM 管线所需
- `JWT_SECRET_KEY` — 生产环境务必修改

### 2. 一键启动（生产模式）

```bash
docker compose up --build -d
```

启动后访问 `http://localhost:8080`。首次启动会自动执行数据库迁移。

### 3. 本地开发

```bash
# 启动 PostgreSQL + Redis
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# 后端
cd backend
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 前端（另一个终端）
cd frontend
npm install
npm run dev
```

前端默认运行在 `http://localhost:5173`，后端 `http://localhost:8000`。

## 项目结构

```
newsforge/
├── backend/
│   ├── app/
│   │   ├── api/              # v1 公开 / admin 管理 / internal 机器接口
│   │   ├── core/             # 配置、认证、限流、LLM 客户端
│   │   ├── models/           # SQLAlchemy ORM
│   │   ├── schemas/          # Pydantic 数据模型
│   │   ├── sources/          # 新闻源适配器（RSS / API）
│   │   ├── content/          # 全文抓取
│   │   ├── pipeline/         # 处理管线（去重、分类、评分、分析…）
│   │   ├── services/         # 业务逻辑
│   │   └── utils/            # 工具函数
│   ├── alembic/              # 数据库迁移
│   └── config/               # pipeline.yml 管线配置
├── frontend/src/
│   ├── components/           # UI 组件
│   ├── pages/                # 页面
│   ├── stores/               # Zustand 状态管理
│   └── i18n/                 # 中英国际化
├── docker/                   # Nginx、Supervisord 配置
├── docker-compose.yml        # 生产编排
├── docker-compose.dev.yml    # 开发编排
└── Dockerfile                # 多阶段构建
```

## 管线配置

处理管线通过 `backend/config/pipeline.yml` 配置，不依赖数据库。可以：

- 切换 LLM 模型和 provider
- 为不同分类配置不同的处理 agent（scorer、analyzer、translator 等）
- 调整触发条件和处理深度

## API

| 路径前缀 | 认证方式 | 说明 |
|----------|---------|------|
| `/api/v1/` | JWT | 公开接口——文章列表、搜索、分类 |
| `/api/admin/` | JWT (admin) | 管理接口——源管理、用户管理 |
| `/api/internal/` | X-API-Key | 机器消费接口——供外部系统拉取/推送 |
| `/api/v1/health` | 无 | 健康检查 |

## License

MIT
