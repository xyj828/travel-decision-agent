# 课后提交材料

本目录是本课程的复现证据（对应手册「十、课后提交」）。

| 文件 | 说明 |
|------|------|
| `local-running.png` | 本地调试页面：`npx edgeone@1.7.6 makers dev` 启动后的入口页（空状态 + 6 个工具指示灯） |
| `normal-result.png` | 正常请求：「我在红莲南路地铁站附近，我想找一个既有倍轻松又有西厅村屋的商场」→ 推荐龙湖北京丽泽天街 1222m，并说明高德实际收录名为「西町村屋」 |
| `follow-up-result.png` | 连续追问：「如果不要求两个品牌同时存在，还有没有距离更近的选择？」→ 保留前一轮地点条件，分别查两个品牌最近门店（1247m / 1218m），并给出翠微一带的次选 |
| `online-entry.png` | 线上公开地址首屏（EdgeOne 临时预览域名） |
| `online-result.png` | 线上问「既有倍轻松又有西厅村屋」的真实回答（1222 米推荐 + 传输流） |
| `public-entry.txt` | 公开预览地址、部署 ID、线上验证记录 |
| `deploy-log.txt` | `edgeone makers deploy` 的完整部署日志（Deploy Success） |
| `deploy-success.png` | Makers 控制台「部署成功」截图（可选：控制台截图，线下补） |

## 关于 `actions-success.png`

手册里要求提交 GitHub Actions 成功截图，但这个 Starter 仓库**没有 `.github/workflows` 目录**，
且本项目是 EdgeOne CLI 创建的「直传」项目，部署通过 `edgeone makers deploy` 完成（见 `deploy-log.txt`），
因此不存在 GitHub Actions 运行记录，用 `deploy-log.txt` + `online-result.png` 作为等价的部署成功证据。

如果后续按控制台提示添加了 CI 模板（并配置 `EDGEONE_API_TOKEN` Secret），再补一张 Actions 截图即可。

## 本地验证命令

```bash
# 只验证高德工具链（不消耗模型额度）
.venv/Scripts/python.exe scripts/check_amap_tools.py

# 验证两轮对话（含追问记忆），需要本地服务已启动
.venv/Scripts/python.exe scripts/test_chat.py
```
