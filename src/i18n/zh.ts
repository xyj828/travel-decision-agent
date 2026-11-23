const zh = {
  // Header
  "app.title": "出行决策 Agent",
  "app.subtitle": "高德地图检索附近商场 · 品牌匹配 · 距离推荐",

  // Empty state
  "empty.title": "出行决策 Agent",
  "empty.hint": "告诉我你在哪、想逛哪些品牌，我会用高德检索附近商场、核对品牌门店、比较距离，推荐最近的那一家。",
  "empty.features": "EdgeOne Store · Session Memory · Agent Tools",

  // Chat input
  "chat.placeholder": "发消息…  ⏎ 发送 · Shift+⏎ 换行",
  "chat.hint": "由 OpenAI Agents SDK + 高德地图 + EdgeOne Makers 驱动",

  // Preset questions
  "preset.1": "我在红莲南路地铁站附近，想找一个既有倍轻松又有西厅村屋的商场。",
  "preset.2": "如果不要求两个品牌同时存在，还有没有距离更近的选择？",

  // Tool indicators
  "tool.locate": "地点定位",
  "tool.mall": "附近商场",
  "tool.brand": "品牌匹配",
  "tool.distance": "距离计算",
  "tool.plan": "综合推荐",

  // Status & errors
  "status.error": "⚠️ 请求失败，请检查后端服务是否启动。",
  "status.stopped": "⏹ *已停止生成*",
  "status.backendError": "⚠️ 后端中断请求失败，服务端可能仍在运行。",

  // Debug panel
  "debug.title": "传输流",
  "debug.events": "事件",
  "debug.clear": "清除",
  "debug.empty": "等待 SSE 事件...",
  "debug.emptyHint": "发送消息后，所有原始后端数据将在此处显示。",

  // Conversation sidebar
  "sidebar.label": "会话列表",
  "sidebar.title": "会话",
  "sidebar.newChat": "新建聊天",
  "sidebar.loading": "正在加载会话...",
  "sidebar.loadMore": "加载更多",
  "sidebar.loadingMore": "加载中...",
  "sidebar.emptyTitle": "暂无会话",
  "sidebar.emptyHint": "点击「新建聊天」开始第一段对话。",
  "sidebar.delete": "删除会话",
  "sidebar.deleteConfirm": "确定要永久删除这个会话吗？此操作不可恢复。",

  // Aria labels (button hover/screen-reader)
  "aria.send": "发送",
  "aria.clearHistory": "清除历史",
  "aria.stopGeneration": "停止生成",

  // Language toggle
  "lang.switch": "English",

  // ─── Floating bottom-right action badges ─────────────────────────────
  "floatingLink.deploy": "一键部署",
  "floatingLink.github": "GitHub",
} as const;

export default zh;
