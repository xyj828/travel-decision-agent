# 出行决策 Agent（Travel Decision Agent）

基于 OpenAI Agents SDK（Python）+ 高德地图 Web 服务 API，跑在 EdgeOne Makers 上的全栈 Agent：用户说出位置和品牌偏好，Agent 检索附近商场、核对品牌门店、比较距离并给出推荐。

## 概述

在原 Starter 模板的流式聊天骨架上，把示例工具换成了真实的高德地图能力：

| 工具 | 作用 |
|------|------|
| `resolve_location` | 地点（地铁站 / 商场 / 地址 / 经纬度）→ 坐标，带歧义候选 |
| `search_nearby_malls` | 坐标 → 附近商场，按距离排序 |
| `match_brands_in_mall` | 某个商场 → 逐个核对品牌门店是否存在 |
| `find_nearest_brand_store` | 单个品牌 → 离用户最近的门店（替代方案用） |
| `get_travel_distance` | 两点 → 直线 / 驾车 / 步行距离与耗时 |
| `find_malls_with_all_brands` | 一站式：位置 + 品牌清单 → 候选商场排名与最佳推荐 |

- **SSE 流式聊天** —— 逐 token 推 `text_delta`，命中工具时推 `tool_called`（前端 6 个工具指示灯）。
- **数据不由模型编造** —— 地点、门店、距离全部来自高德返回，工具失败时如实说明原因。
- **同音字容错** —— 用户说「西厅村屋」、高德收录「西町村屋」时，工具会用近似匹配 + 全城检索兜底，并在结果里标注 `name_match: similar`。
- **限速与重试** —— 高德个人 Key 约 3 QPS，工具内置 0.4s 全局节流与 QPS 超限退避重试，多品牌并发核对不会被限流打断。
- **会话粘性记忆** —— `context.store.openai_session(cid)` 直接喂给 `Runner.run_streamed()` 的 `session` 参数，支持「不要求两个品牌同时存在呢」这类追问。
- **可信取消** —— 后端 `context.utils.abort_active_run()` 真正中断 LLM 调用。
- **后端拆两层** —— 有状态的长连接放 `agents/`，无状态的 `/history` 放 `cloud-functions/`。

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `AI_GATEWAY_API_KEY` | 是 | 模型网关 API Key。可填 Makers Models 的 API Key，也可以是任意 OpenAI 兼容服务商的 Key。 |
| `AI_GATEWAY_BASE_URL` | 是 | 网关 Base URL。Makers Models 请使用 `https://ai-gateway.edgeone.link/v1`。 |
| `AI_GATEWAY_MODEL` | 否 | 模型 ID。默认 `@makers/deepseek-v4-flash`（内置免费模型）。 |
| `AMAP_API_KEY` | 是 | 高德「Web 服务」类型的 Key。高德控制台 → 应用管理 → 添加 Key → 服务平台选 **Web服务**。 |

模板遵循 OpenAI 兼容协议，可以指向 Makers Models，也可以指向任意 OpenAI 兼容的服务商。

## 地图工具自检（不消耗模型额度）

填好 `.env` 里的 `AMAP_API_KEY` 后执行：

```bash
.venv/Scripts/python.exe scripts/check_amap_tools.py
# 自定义起点与品牌
.venv/Scripts/python.exe scripts/check_amap_tools.py --location "红莲南路地铁站" --brands "倍轻松,西厅村屋"
```

它会依次验证定位、商场检索、品牌匹配、距离计算、一站式推荐，并把高德的真实错误码翻译成可读原因。

### 如何获取 `AI_GATEWAY_API_KEY`

1. 打开 [Makers 控制台](https://console.cloud.tencent.com/edgeone/makers)。
2. 登录并开通 Makers。
3. 进入 **Makers → Models → API Key**，新建一个 Key。
4. 把它粘到 `AI_GATEWAY_API_KEY`。

内置的 `@makers/deepseek-v4-flash` 免费但有用量限制，适合验证；生产建议自行绑定付费厂商（BYOK）。

## 本地开发

前置依赖：Node.js ≥ 18、Python ≥ 3.10。EdgeOne CLI 用 `npx edgeone@1.7.6` 调用即可（首次自动下载，无需全局安装）。

```bash
# 1. 依赖（本机已装好可直接跳过）
npm install
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip

# 2. 首次登录腾讯云（浏览器确认，只需一次）
npx edgeone@1.7.6 login

# 3. 本地启动（会自动同步 Makers 控制台的 AI Gateway Key 与环境变量）
npx edgeone@1.7.6 makers dev
```

首次启动会询问要绑定的项目；若控制台里已经创建了 `travel-decision-agent` 项目，直接选择它。
本地观测面板：`http://localhost:8080/agent-metrics`。

> `.env` 里只需自己填 `AMAP_API_KEY`；`AI_GATEWAY_API_KEY` 一般由 `makers dev` 自动写入。
> 也可以手动在 Makers 控制台 → 模型与密钥 生成后粘贴。

## 项目结构

```text
openAI-agent-starter-python/
├── agents/                          # 有状态的 EdgeOne Makers Agent Functions（Python）
│   ├── chat/index.py               # POST /chat —— SSE 流式聊天
│   ├── chat/stop.py                # POST /chat/stop —— 中断当前 agent
│   ├── _logger.py                  # 日志工具（私有）
│   └── _tools.py                   # Agent 工具定义（私有）
├── cloud-functions/                 # 无状态的 EdgeOne Makers Python cloud functions
│   ├── history/index.py            # POST /history —— 拉取对话消息
│   └── _logger.py                  # 日志工具
├── src/                             # React + Vite + TypeScript 前端
│   ├── App.tsx                     # 主应用 + SSE 流生命周期管理
│   ├── api.ts                      # /chat、/chat/stop、/history 接口封装
│   └── components/                 # ChatWindow、ChatInput、CodeViewer、ToolIndicators 等
├── package.json                     # 前端依赖
├── requirements.txt                 # Python 依赖
├── edgeone.json                     # framework=openai-agents-sdk
├── vite.config.ts
├── tsconfig.json
└── .gitignore
```

> 以 `_` 开头的文件是私有模块，不会暴露为公开路由。

## 资源

- [EdgeOne Makers Agents 文档](https://cloud.tencent.com/document/product/1552/132759)
- [EdgeOne Makers 快速开始](https://cloud.tencent.com/document/product/1552/132786)
- [Makers Models](https://cloud.tencent.com/document/product/1552/132748)

## License

MIT.
