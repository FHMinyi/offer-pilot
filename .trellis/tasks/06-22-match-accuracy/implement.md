# 匹配准确度修复 · 实施清单（implement.md）

> 顺序原则：**可复现地基先稳（不碰大模型）→ 大模型逐层叠加**。
> 每个 Stage 可独立验收；时间紧时从下往上砍（先保住 Stage 1 的"准且可复现"）。
> 每 Stage 结束跑后端测试 + 记 `docs/修改日志/`，并设回滚点（git 提交边界）。

## Stage 0 · 基线与样例（验收地基）

- [ ] 建一组**代表性样例**：N 份简历 × 岗位组合，含已知病例（"FastAPI+Redis 后端" vs "精通Python，熟悉Redis，了解Docker"），写下每例的**期望区间**（如该简历应 ≥70%、Redis 应出现在已具备、Docker 应为加分缺口）。落到测试夹具。
- [ ] 跑现状基线，记录每例当前输出（17%、Redis 消失等），作为对照。
- **回滚点**：纯新增测试，无行为改动。

## Stage 1 · 可复现地基（规则，不碰大模型）—— 修 P1/P2/P3 + P4/P5 规则侧

> 这一层做完，"规则模式"就已经准且可复现，是性价比最高的一刀。

- [ ] **②本体重构**（`data/skills.py`）：拆出独立节点（fastapi/flask/django/redis/mongodb…），改正 `category`，加 `implies` 关系字段；移除 `database`/`python` 里的错误别名。保留旧 key 兼容已存 `skill_key`。
- [ ] **②归一输出关系**（`services/skills.py`）：`match_skills`/`normalize_terms` 输出规范节点 + `implies` 闭包。
- [ ] **③评分重做**（`gap_analysis.py`）：重写 `_score`（去必备数量稀释）；按 `strength(project>work>listed)` 加权；岗位必备可由 `implies` 技能满足；弱化/删除 `_project_skill_keys` 的重猜。
- [ ] **P3 验证**：Redis 不再与 SQL 撞 key，`jd_parser.py:41` 去重不再误删。
- [ ] **P4 规则侧**（`jd_parser._classify_lines`）：从"整行 must/nice"改为"技能附近窗口"判定。
- [ ] **P5 规则侧**（`resume_parser`）：项目/经历段命中技能标 `project/work`、技能栏标 `listed`；增强项目段识别鲁棒性。
- [ ] 跑 Stage 0 样例：每例落入期望区间；跑后端既有测试全绿；新增针对性用例。
- **验收**：规则模式下 17%/Redis 消失/Docker 误必备 全部消除，且**同输入多次跑同分**。
- **回滚点**：提交 `fix(匹配): 评分与本体重构（规则地基）`。

## Stage 2 · 大模型抽取增强（①）

- [ ] 改 `resume_parser._parse_with_llm` 提示与输出：每技能带 `{raw, evidence_text, strength}`。
- [ ] 改 `jd_parser._parse_with_llm`：每技能带 `{raw, requirement(must/nice), cue}`，必备/加分下沉到技能级（修 P4 的大模型侧）。
- [ ] 抽取结果接入②③；确认 `Resume.structured` 持久化复用仍生效（可复现闸一）。
- [ ] 大模型模式跑 Stage 0 样例：质量 ≥ 规则模式；与规则模式契约一致。
- **验收**：配密钥下抽取带强度，③直接消费、不再重猜。
- **回滚点**：提交 `feat(匹配): 大模型抽取带证据强度`。

## Stage 3 · 归一活表（②的大模型补缺 + 钉死）

- [ ] 建 DB 表 `skill_norm`（`raw_term/canonical_key/implies/category/source/status/created_at`），过 `db_guard`。
- [ ] ②查找链：seed 本体 → `skill_norm` → 未命中调大模型判断 → 写表钉死 → 复用。
- [ ] 写入前查重（避免与 seed/已有条目撞车）；无大模型时走 free-form 兜底不阻断。
- [ ] 验证可复现：新词首次入表后，重跑同分；表已稳定时零额外大模型调用。
- **验收**：本体外新技能能被正确归一并钉住，可复现不破。
- **回滚点**：提交 `feat(匹配): 归一活表（大模型判断+持久化）`。

## Stage 4 · 复核回路（④）

- [ ] 建 DB 表 `scoring_issue`（`analysis_run_id/issue_type/skill_key/evidence/suggestion/status/created_at`），过 `db_guard`。
- [ ] `agent.py` 的 `analyze_match` 产出 report 后，增加"复核"步：大模型用对话+联网上下文复核分与证据 → 产出「AI 复核意见」（对话气泡）+ 写 `scoring_issue`（结构化）。
- [ ] 约束复核提示：仅在发现具体问题时记录，否则简短确认（控噪声）。
- [ ] 复用 usage/归属上下文；复核不改权威分。
- **验收**：复核意见出现在对话、问题记录正确落库、权威分不变。
- **回滚点**：提交 `feat(匹配): 大模型复核回路`。

## Stage 5 · 受控优化（⑤）【默认受控，待 review 确认】

- [ ] 提供 `scoring_issue` 的查看/评审入口（CLI 或简单接口均可）。
- [ ] 评审 → 据 `suggestion` 改 `skill_norm`/评分参数 → 过测试 → 合入 → 标 `applied`。
- [ ] 文档化"受控合入"流程（不在运行时静默改规则）。
- **验收**：问题记录能闭环回流到②③并被测试守住。
- **回滚点**：提交 `feat(匹配): 受控规则优化闭环`。

## 全局验收（对照父任务跨线项之一）

- [ ] 不再出现"过得去简历 17%""Redis 消失""Docker 误必备"。
- [ ] 同输入多次运行同分（可复现）。
- [ ] 每条结论可解释（证据 + 来源）。
- [ ] 后端测试全绿；改动均记 `docs/修改日志/`。

## 验证命令（占位，start 时核实确切命令）

- 后端测试：项目既有 pytest 套件（`backend/` 下）。
- 样例回归：Stage 0 夹具断言期望区间。
