# 演示素材（截图 / GIF）

主 README 引用本目录下的图片。当前是 **SVG 占位图**，请按下文录制真实素材后替换。

## 一键准备「活」的演示状态

录制前先播种一份有任务、打卡、进度的演示数据（详见 `backend/seed_demo.py`）：

```bash
./scripts/dev-backend.sh      # 终端 1：起后端（首次会建 venv 装依赖）
./scripts/dev-frontend.sh     # 终端 2：起前端
./scripts/seed-demo.sh        # 终端 3：播种演示数据（输出会打印可访问的 /plan/<id>）
```

播种脚本会清空 `user_id='local'` 的旅程/任务/打卡三表并重建一条演示旅程：约 30 个任务、
3 个已完成、最近 4 天打卡（含一个空档）、4 条逾期任务被动态再规划顺延——
保证看板与计划页一打开就「有内容、有故事」。

## 需要录制的素材

| 文件 | 页面 | 建议内容 |
|---|---|---|
| `demo.gif` | 端到端 | 粘贴简历+JD → 流式分析出报告 → 生成学习方案 → 进计划页勾选/结算 → 看进度看板 |
| `chat.png` | `/`（对话） | 流式分析中：工具调用过程 + 结构化报告卡 + 语气滑块 |
| `plan.png` | `/plan/<runId>` | 今日任务 + 「结算今天并重排」+ 逾期顺延提示 + 每日打卡卡片 |
| `dashboard.png` | `/dashboard` | 完成率环 + 最近 7 天热力 + 五阶段步骤条 + 节奏洞察 |

## 录制建议

- **GIF**：用 [`asciinema`](https://asciinema.org/) 不适合 UI；推荐 [Peek](https://github.com/phw/peek)（Linux）、
  [LICEcap](https://www.cockos.com/licecap/)（跨平台）或系统自带屏录后用 `ffmpeg` 转 GIF：
  ```bash
  ffmpeg -i demo.mp4 -vf "fps=12,scale=1200:-1:flags=lanczos" -loop 0 docs/assets/demo.gif
  ```
- 录制窗口建议 1200×675（16:9），与占位图同比例，替换后排版不跳动。
- 截图替换后，把主 README 中对应的 `.svg` 链接改成 `.png` / `.gif` 即可。
