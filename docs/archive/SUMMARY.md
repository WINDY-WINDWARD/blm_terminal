# Archive Index & Historical Reference Summary

This directory contains historical design documents, implementation plans, context files, and progress logs for completed features in `blm_terminal`.

> [!NOTE]
> All documents in this directory are preserved for historical reference and architectural decision context. For active code conventions and repository guidelines, see [AGENTS.md](file:///d:/500GB/p1/Projects/blm_terminal/AGENTS.md) and [README.md](file:///d:/500GB/p1/Projects/blm_terminal/README.md).

---

## Document Index & Active Code Mappings

### 1. Feature Expansions & Core Architecture
* **[BuildMemory.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/BuildMemory.md)**: Notes on build memory optimizations and performance.
* **[FeatureExpansionPlan.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/FeatureExpansionPlan.md)**: Plan for terminal feature expansions (AI Personas, Valuation Tab, Portfolio Optimizer).
* **[FeatureExpansionHandoff.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/FeatureExpansionHandoff.md)**: Handoff documentation and architectural details for expanded features.
  - **Active Code Mappings**:
    - AI Personas / AI Chat: [AiWidget.tsx](file:///d:/500GB/p1/Projects/blm_terminal/src/components/widgets/AiWidget.tsx), [ai_chat.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/ai_chat.py), [ai_chat_service.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/services/ai_chat_service.py)
    - Valuation: [ValuationWidget.tsx](file:///d:/500GB/p1/Projects/blm_terminal/src/components/widgets/ValuationWidget.tsx), [valuation.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/valuation.py)
    - Portfolio Optimizer: [PortfolioWidget.tsx](file:///d:/500GB/p1/Projects/blm_terminal/src/components/widgets/PortfolioWidget.tsx), [portfolio.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/portfolio.py)

### 2. Background Tasks & Infrastructure
* **[background-task-offload-plan.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/background-task-offload-plan.md)**: Architecture for offloading long-running jobs to background worker threads.
* **[jobs-table-plan.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/jobs-table-plan.md)**: Database schema and API specification for tracking background jobs.
* **[notification-feature-plan.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/notification-feature-plan.md)**: Implementation plan for system notifications and alerts.
  - **Active Code Mappings**:
    - Central Orchestrator & Workers: [orchestrator.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/orchestrator.py), [backgroundtasks.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/backgroundtasks.py), [lifecycle.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/workers/lifecycle.py)
    - Jobs API & Tracking: [jobs.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/jobs.py), [jobs/route.ts](file:///d:/500GB/p1/Projects/blm_terminal/src/app/api/jobs/route.ts)
    - Notifications: [NotifWidget.tsx](file:///d:/500GB/p1/Projects/blm_terminal/src/components/widgets/NotifWidget.tsx), [notifications.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/notifications.py), [notifications/route.ts](file:///d:/500GB/p1/Projects/blm_terminal/src/app/api/notifications/route.ts)

### 3. Live Charting & Technical Indicators
* **[live-charting-PLAN.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/live-charting-PLAN.md)**: Implementation plan for real-time live charting.
* **[live-charting-CONTEXT.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/live-charting-CONTEXT.md)**: Architecture context and WebSocket stream mapping for charts.
* **[live-charting-MEMORY.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/live-charting-MEMORY.md)**: Execution memory and status log for live charting development.
* **[live-charting-PLAN_INTRADAY_INDICATORS.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/live-charting-PLAN_INTRADAY_INDICATORS.md)**: Calculation and streaming of intraday technical indicators.
  - **Active Code Mappings**:
    - Frontend Chart Component: [ChartWidget.tsx](file:///d:/500GB/p1/Projects/blm_terminal/src/components/widgets/ChartWidget.tsx)
    - WebSocket Service & Proxy: [marketWs.ts](file:///d:/500GB/p1/Projects/blm_terminal/src/lib/marketWs.ts), [server.js](file:///d:/500GB/p1/Projects/blm_terminal/server.js)
    - Backend NSE Chart Client & Indicators: [nse_charting_client.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/services/nse_charting_client.py), [indicators.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/services/indicators.py)

### 4. Multi-Source News & External Feeds
* **[multi-source-news-PLAN.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/multi-source-news-PLAN.md)**: Plan for multi-source news aggregator (iinvest, MoneyControl, RSS).
* **[multi-source-news-CONTEXT.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/multi-source-news-CONTEXT.md)**: Context and data schema for news streams.
* **[multi-source-news-IMPLEMENTATION.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/multi-source-news-IMPLEMENTATION.md)**: Detailed implementation log for news aggregation.
* **[multi-source-news-MEMORY.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/multi-source-news-MEMORY.md)**: Execution progress log for news feature development.
  - **Active Code Mappings**:
    - Frontend News Widget: [NewsWidget.tsx](file:///d:/500GB/p1/Projects/blm_terminal/src/components/widgets/NewsWidget.tsx)
    - WebSocket & API Services: [newsSocket.ts](file:///d:/500GB/p1/Projects/blm_terminal/src/lib/newsSocket.ts), [news_ws.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/news_ws.py), [news.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/news.py)
    - Aggregator & Sources: [news_aggregator.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/services/news_aggregator.py), [iinvest_client.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/services/iinvest_client.py), [moneycontrol_client.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/services/moneycontrol_client.py)

### 5. Valuation & External Data Integration
* **[morningstar-fair-value-plan.md](file:///d:/500GB/p1/Projects/blm_terminal/docs/archive/morningstar-fair-value-plan.md)**: Integration plan for Morningstar fair value and uncertainty metrics.
  - **Active Code Mappings**:
    - Morningstar Client & Router: [morningstar_client.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/services/morningstar_client.py), [morningstar.py](file:///d:/500GB/p1/Projects/blm_terminal/backend/app/routers/morningstar.py)
