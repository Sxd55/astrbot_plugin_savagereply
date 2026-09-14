# Savage's Reply 项目约定

AstrBot 发送前「最后一公里」的人味化插件。核心两件事：

1. **智能分段连发 + 打字延迟**：把 LLM 长回复切成短句逐条发送，像真人打字聊天。
2. **正文完整性优先**：代码块 / 表格 / 公式 / 超长文一律不拆，绝不因拟人化丢内容。

## 边界（明确不做）

- 不碰记忆、人格、上下文注入（那是 Savage Type 的职责）。
- 不处理非 LLM 结果；含图片 / 语音 / 转发等非文本组件的消息原样放行。
- 不自动修改 AstrBot 全局配置。检测到内置 `segmented_reply` 开启时只警告"双重分段"。
- v0.x 不做管理面板，配置全走 WebUI 插件设置。

## 结构约定

```text
main.py                 Star 入口：on_decorating_result 钩子、chain 操作、逐段发送、Web API
savagereply/
  __init__.py           PLUGIN_NAME / __version__
  config.py             配置归一化：ReplyOptions dataclass + 类型容错 + 范围钳制
  policy.py             纯函数分流：bypass / split（规则见下）
  segment.py            纯函数分段引擎：保护区扫描 + 区间断点 + 短尾合并 + 段数上限
  pacing.py             纯函数延迟模型：字数 × 每字时间 × 抖动，含单条/总帽
  marker.py             纯函数边界标记：[[next]] 解析（代码块内不生效）+ 输出规范提示
  typing_status.py      输入状态封装：aiocqhttp 私聊 set_input_status，失败静默
  verify.py             纯函数风险扫描：可疑承诺 / 无出处统计 / 未提及链接，只记录不阻塞
pages/lookbook/         插件页面「输出画廊」：index.html + style.css + app.js + silk.js + assets/（丝绸视频，素材来自 StyleKit MIT）
tests/test_core.py      离线测试，只用标准库：python tests/test_core.py -v
```

## 关键机制（改动前必读）

- **钩子**：`@filter.on_decorating_result(priority=-100000000000000000)` 全场最低，保证
  在其他插件改完 chain 后执行；在内置分段 / TTS / 转图 / 合并转发之前。
- **发送模式**：前 N-1 段自行 `event.send()` 后 sleep；**最后一段留在 `result.chain`** 交还
  框架发送（保留框架的 at / 引用 / 平台适配行为，风险最小）。参照 splitter 的成熟做法。
- **防重入**：在 `result` 对象上打 `__savagereply_processed` 标记。不要用 event 级锁——
  Agent 工具调用会在同一 event 上产生多个 result 实例。
- **发送失败不丢内容**：任何一段 `event.send()` 抛异常，立即停止分段，把剩余各段合并塞回
  `result.chain` 让框架兜底发送。
- **TTS 兼容**：`_tts_active` 探测（全局 TTS 开关 + 会话开关 + provider 存在）。激活时
  不自行发送，把各段拆成多个 Plain 塞回 `result.chain`，框架会逐段转语音再发——
  否则会出现"前半截文字 + 最后一段语音"的混合。
- **内置分段兼容**：`_builtin_segmented_enabled` 为真时 `hand_back=False`，最后一段也
  自行发送并清空 chain，避免框架把最后一段二次切碎；加载时日志提示建议关闭内置分段。
- **边界标记**：`on_llm_request` 每轮注入输出规范（`extra_user_content_parts` + `mark_as_temp`，
  不写历史不碰人格）；`_decorate` 里先用 `parse_marker` 解析，有效切分（≥2 段）时每段再走
  `segments_from_marked`（内部仍过保护区引擎），否则回落本地 policy/split。`silk` 代码块内的
  标记不生效也不移除。
- **打字状态**：`_send_segments` 在段间 sleep 前调 `set_input_status(1)`、finally 清理(0)；
  仅 aiocqhttp 私聊（`should_show_typing`），且 `delay_enabled` 关闭时跳过（没有等待就没有意义）；
  平台不支持或调用失败全部静默。
- **插件页面**：`pages/lookbook/`，经 `window.AstrBotPluginPage` 桥与插件 Web API 通信。
  后端只允许页面写 `BOOL_CONFIG_KEYS` 这 8 个布尔键（白名单），数值参数一律不可经页面修改。
  风格约束：Luxe Lookbook（瓷白 #F7F5F1 / 墨黑 #141210 / 唯一哑光金 #9A7B4F / 方角 /
  hairline / 无圆角阴影渐变 / 无 font-bold），改样式前先对照该规范自查。
  页面坑位（血泪）：`.boot` / `.sheet` 这类 `position:fixed + display:grid` 的元素上，
  `hidden` 属性会被作者样式覆盖导致透明层全屏拦截点击——样式表里必须有
  `[hidden] { display: none !important; }`。画册用原生横向滚动（不要改回 sticky 滚动驱动，
  实机卡顿；滚轮是逐帧翻页，不要用 scrollLeft 累加，会被 scroll-snap 吸回）；所有点击
  目标 ≥ 44px。五帧底色 = 色板五色（Porcelain/Stone/Taupe/Gold/Ink），深底需用
  `.tone-*` 选择器切换文字与细线颜色。
  **丝绸背景 = 真实素材动图（silk-anim.webp，StyleKit MIT）+ CSS 漂移层兜底**：
  `<img class="silk-anim">` 由浏览器自动循环——**img 动画不受 iframe sandbox autoplay 限制**，
  打开即流动、零 JS。`.silk-fallback`（双层静态图漂移）垫底，动图失败时可见；
  reduced-motion 隐藏动图只留静态层。**不要用 `<video>`**：sandbox（allow-scripts
  allow-forms allow-downloads）无 allow-autoplay，自动播放被拦、必须用户点击，实测不可靠；
  动图是唯一"真素材 + 自动播放"的形态。动图由 silk.webm 用 ffmpeg 转制（fps=30 原帧率、
  1280 宽、libwebp q72、loop 0，约 940KB）。AstrBot 只重写 src/href，别用 poster 属性；
  CSS url() 可安全引用 assets。
- **延迟语义**：打字延迟由 `delay_enabled` 总控（默认开，关时 `segment_delay` 返回 0，
  分段直接连发）。开启时首段不等待；`sleep` 的时间按**下一段**文本计算（模拟"打完这段
  才发下一条"）；总延迟有帽（默认 10s），超帽后直接连发。sleep 在钩子内执行，会阻塞
  本会话管线——短延迟可接受，会话本来就是串行的。
- **分段原则**：保护区（``` 代码块、行内 `code`、$公式$、<think> 块、行首 | 表格行）内
  绝不下刀；断点优先级：空行 > 换行 > 。？！…~ > ，、；弹性延伸至硬上限后强制断；
  短尾（≤8 字）并回上一段；段数超上限时尾部合并。
- **分流规则**（policy.py，顺序即优先级）：
  1. 含代码块 → bypass（代码块和说明文字被拆开发送顺序会乱）
  2. 含 Markdown 表格 → bypass
  3. 含 `$$` 块级公式 → bypass
  4. 字数 > `max_total_chars` → bypass（预防超长被平台截断）
  5. 字数 < `min_total_chars` → bypass
  6. 其余 → split

## 防幻觉边界（已评审）

- 完整防幻觉体系（RAG / 微调 / 解码参数 / NLI 核查）**不属于本插件**：
  RAG 归 Savage Type / AstrBot 知识库，提示词归人格，搜索归工具。
- 本插件只做出口层的最小防护：`verify.py` 纯正则风险扫描（默认关）。
  评审结论见 README「防幻觉」章节，不要再往插件里加模型核查调用——
  每条回复 1~3 秒延迟 + 翻倍成本，与「像真人秒回」的核心目标冲突。

## 代码风格

- Python 3.11+，只用标准库；核心逻辑必须是纯函数，便于离线测试。
- 配置读取只经 `config.py`，不在业务代码里裸读 dict。
- 日志统一英文、带 `Savage's Reply` 前缀；debug 细节走 `debug_log` 开关。
- 类型标注 + dataclass；不为兼容旧版写降级分支（AstrBot >= 4.22）。

## 测试

```text
python tests/test_core.py -v
```

覆盖：保护区（代码块 / 表格 / 公式 / 括号 / 引号）、中英混排、URL、超长无标点、
短尾合并、段数上限、标点吸附、延迟边界（注入 seed 的 rng）、policy 各分流条件。

## 版本与发布

- 版本在 `savagereply/__init__.py` 与 `metadata.yaml` 同步维护。
- 提交信息用中文简述；仓库 `Sxd55/astrbot_plugin_savagereply`。
