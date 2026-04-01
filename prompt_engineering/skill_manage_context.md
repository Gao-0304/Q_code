#### 2. 短期记忆动态追踪技能 (`skill_manage_context.md`)
*触发条件：在任何连续实验的步骤切换时，或寻优参数更新时执行。*
```markdown
# 技能：短期记忆动态追踪 (Short-Term Memory Tracking)
## 触发时机
1. 接收到包含多个测量步骤的新任务时（初始化队列）。
2. 任何一个子实验（如 Rabi 扫频）完成，并得到拟合参数后。
## 执行逻辑
你需要静默（I 级权限）通过 `agent_manager.py update_short_term` 更新 `memory/short_term_context.md` 文件。该文件充当你的“草稿本”和“状态机”。
## 更新规则
1. **任务队列 (Task Queue)**：使用 Markdown 的 Checkbox 语法 (`- [ ]`, `- [x]`) 动态维护当前批次实验的进度。不要删除已完成的任务，而是打上勾。
2. **参数黑板 (Parameter Blackboard)**：
   - 每次数据处理脚本返回新的优化参数（例如：测完了 Resonator 找到了最佳频率，或测完 Rabi 确定了 $\pi$ 脉冲时长），立即更新到此区域。
   - 明确标注参数的来源（例如：“来自实验1拟合”）。
3. **文件指针 (File Pointers)**：记录最新生成的 QCoDeS 数据库文件 (`.db` 或 `.h5`) 路径和绘图结果路径，方便下一个脚本调用。
4. **预检追踪 (Precheck Tracking)**：每次测量前，记录 `tools/planner_and_plotter.py` 生成的最新文件路径：
   - `measurement/operation/pulse_sequence_*.png`
   - `measurement/operation/operation_summary_*.json`
   并标注人工确认结果（`Y` 或 `N`）。若为 `N`，任务队列对应测量步骤不得打勾。
5. **执行器追踪 (Executor Tracking)**：每次调用 `tools/qcodes_executor.py` 后，记录：
   - 被执行的脚本路径（`script_path`）
   - 执行日志路径 `measurement/operation/qcodes_executor.log`
   - 开始时间、预计时长（若可解析）和最终状态（成功/失败）
6. **经验缓存 (Experience Cache)**：当得到可复用经验或踩坑记录时，必须调用 `agent_manager.py cache_experience` 写入 `memory/temp_experience_cache.md`，不允许直接写入长期库。
7. **长期合并 (Long-term Commit)**：批次任务完成后，调用 `agent_manager.py commit_long_term`，并等待用户在终端输入 `Y/N`。仅当 `Y` 时，允许合并到 `memory/long_term_skills.md`。
## 严格限制
- 每次实验开始前，你必须先读取此文件，将“参数黑板”中的数值作为下一步实验的默认设置，绝对禁止从文献中瞎猜物理量。
- 每次实验开始前，若未找到最近一次预检 JSON 或确认结果不是 `Y`，禁止进入测量执行步骤。
- 若最近一次执行器状态为失败，必须先修复脚本或参数再重试，禁止直接跳过失败记录继续测量。
- 严禁绕过 `agent_manager.py` 直接编辑 `memory/short_term_context.md`、`memory/temp_experience_cache.md`、`memory/long_term_skills.md`。