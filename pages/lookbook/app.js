/* Savage's Reply · Lookbook —— 画册页交互
   无依赖：原生滚动 + IntersectionObserver 之外只用滚动计算。
   bridge: window.AstrBotPluginPage（AstrBot 官方插件页桥）。 */

const FRAMES = [
  {
    id: "segment",
    no: "01",
    zh: "分段连发",
    en: "Segmentation",
    tone: "porcelain",
    desc: "把 LLM 长回复按语义切成短句，逐条发出——像真人一句一句说。",
    points: [
      "保护区扫描：代码块、行内代码、公式、思维链、表格、URL 与成对符号内部绝不下刀",
      "理想区间断句：15–50 字寻找最强停顿；找不到则弹性延伸，120 字强制落刀（为保住单词可再让 32 字）",
      "英文单词、数字、量词不会被切两半；断点后接「和/因为/所以…」或「它/其/该」时不切开",
      "末段不足 8 字并回上一段（问句不并）；段数上限 6，超出自动合并防刷屏",
      "超长回复改按空行段落切（每条 ≤ 180 字），不再整篇放行；超过 4 倍上限才整条发",
      "发送失败时剩余内容合并交还框架兜底，绝不丢内容",
      "模型端可选：注入输出规范后，模型可用 [[next]] 自己决定断句边界（不遵守则回落本地引擎）",
    ],
    keys: [
      { key: "enabled", name: "总开关", hint: "关闭后完全放行，不做任何处理。" },
      {
        key: "force_non_streaming",
        name: "本会话关闭流式",
        hint: "流式内容框架已逐块发出、插件改不动，会出现 [[next]] 泄漏；开启后整段输出再分段。",
      },
      {
        key: "marker_enabled",
        name: "边界标记",
        hint: "每轮临时注入输出规范，模型可用 [[next]] 自己断句；不占人格文件。",
      },
    ],
    facts: [
      ["分段区间", (c) => `${c.segment_min_chars ?? "—"} – ${c.segment_max_chars ?? "—"} 字`],
      ["硬上限", (c) => `${c.segment_hard_max_chars ?? "—"} 字`],
      ["段数上限", (c) => `${c.max_segments ?? "—"} 段`],
    ],
  },
  {
    id: "pacing",
    no: "02",
    zh: "打字延迟",
    en: "Pacing",
    tone: "stone",
    desc: "段与段之间按「打完下一段」的时间等待，第一条前还有「读消息」停顿。",
    points: [
      "延迟 = 基础 0.4s ＋ 每字 0.08s ＋ 句末停顿 0.25s，再乘 80%–120% 随机抖动",
      "首条前随机停 0.5–1.5 秒（读消息 + 组织语言）——真人不会秒回",
      "单条延迟上限 4 秒；整轮总等待上限 10 秒，超出后直接连发",
      "等待发生在发送钩子内，会短暂占用该会话管线——这是「正在打字」的代价",
      "等待期间显示「正在输入」：NapCat 私聊走平台接口，其它平台走框架 typing",
      "关闭后分段仍然连发，只是不再等待",
    ],
    keys: [
      {
        key: "delay_enabled",
        name: "打字延迟",
        hint: "关闭后各段立即连发，节奏由平台决定。",
      },
      {
        key: "typing_enabled",
        name: "打字状态",
        hint: "私有平台可显示「对方正在输入」；不支持的平台自动跳过。",
      },
    ],
    facts: [
      ["每字打字", () => "0.08 s"],
      ["首条停顿", (c) => `${c.read_delay_min_seconds ?? "—"} – ${c.read_delay_max_seconds ?? "—"} s`],
      ["单条上限", () => "4.0 s"],
      ["总上限", () => "10.0 s"],
    ],
  },
  {
    id: "integrity",
    no: "03",
    zh: "完整性保护",
    en: "Integrity",
    tone: "taupe",
    desc: "干正事的回复保持完整——代码、表格、公式与超长正文一律不拆。",
    points: [
      "含代码块 / 表格 / 块级公式的回复整条一次发出，绝不碎片化",
      "超长正文（> 最长分段字数）按空行段落切成 ≤ 180 字的几条，不切碎也不放行",
      "超过 4 倍字数上限（多半是粘贴数据/日志）才整条发出",
      "保护优先于一切处理，是插件的最高优先级",
    ],
    keys: [
      { key: "protect_code_block", name: "保护代码块", hint: "含 ``` 的回复整条发送。" },
      { key: "protect_table", name: "保护表格", hint: "含 Markdown 表格的回复整条发送。" },
      { key: "protect_math", name: "保护公式", hint: "含 $$ 块级公式的回复整条发送。" },
    ],
    facts: [
      ["最长分段字数", (c) => `${c.max_total_chars ?? "—"} 字`],
      ["保护项", () => "代码 · 表格 · 公式"],
    ],
  },
  {
    id: "verify",
    no: "04",
    zh: "出口安检",
    en: "Risk Scan",
    tone: "gold",
    desc: "发送前用纯规则扫描可疑内容——零延迟、零成本、只记录不阻塞。",
    points: [
      "三类模式：可信度承诺（100% / 包治 / 稳赚）、无出处的统计声明、用户没提过的链接",
      "默认只写日志；可切换为在回复末尾追加一句不确定提示",
      "不做事实核查、不联网、不改写正文——那是上游知识库与搜索的职责",
    ],
    keys: [
      { key: "verify_enabled", name: "风险扫描", hint: "命中只记录，不阻塞发送。" },
      {
        key: "verify_log_only",
        name: "仅记录",
        hint: "关闭后命中会在回复末尾追加不确定提示。",
      },
    ],
    facts: [
      ["命中词示例", () => "100% · 包治 · 稳赚"],
      ["处置", () => "记录 / 提示"],
    ],
  },
  {
    id: "scope",
    no: "05",
    zh: "会话与平台",
    en: "Scope",
    tone: "ink",
    desc: "分段只发生在该发生的地方；其余场景一律原样放行。",
    points: [
      "仅处理 LLM 回复；命令回复与系统提示保持原样",
      "图片、语音、合并转发等非文本消息不碰",
      "平台排除：QQ 官方等不支持多条连发的平台自动跳过",
      "会话黑名单：名单内的会话永远不分段",
    ],
    keys: [
      { key: "only_llm", name: "仅处理 LLM 回复", hint: "命令与提示原样发送。" },
    ],
    facts: [
      ["跳过平台", (c) => `${(c.platform_exclude || []).length} 个`],
      ["会话黑名单", (c) => `${(c.session_blacklist || []).length} 条`],
      ["数值微调", () => "设置页"],
    ],
  },
];

const $ = (sel) => document.querySelector(sel);
const strip = $("#strip");
const sheet = $("#sheet");

let CONFIG = {};
let bridgeMissing = false;

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);

async function apiGet(route) {
  const bridge = window.AstrBotPluginPage;
  if (!bridge?.apiGet) throw new Error("bridge unavailable");
  const result = await bridge.apiGet(route);
  if (result && result.status === "error") throw new Error(result.message || "error");
  return result && result.data !== undefined ? result.data : result;
}

async function apiPost(route, body) {
  const bridge = window.AstrBotPluginPage;
  if (!bridge?.apiPost) throw new Error("bridge unavailable");
  const result = await bridge.apiPost(route, body);
  if (result && result.status === "error") throw new Error(result.message || "error");
  return result && result.data !== undefined ? result.data : result;
}

function toast(message) {
  const el = $("#toast");
  if (!el) return;
  el.hidden = false;
  el.textContent = message;
  requestAnimationFrame(() => el.classList.add("toast-on"));
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    el.classList.remove("toast-on");
    toast._timer = setTimeout(() => {
      el.hidden = true;
    }, 650);
  }, 2200);
}

function stateOf(frame) {
  const keys = frame.keys.map((item) => item.key);
  if (!keys.length) return "read";
  const on = keys.filter((key) => CONFIG[key]).length;
  if (on === keys.length) return "on";
  if (on === 0) return "off";
  return "mixed";
}

function stateLabel(state) {
  if (state === "on") return "On";
  if (state === "off") return "Off";
  if (state === "mixed") return "Part";
  return "Read";
}

function frameHTML(frame) {
  const state = stateOf(frame);
  return `
    <article class="frame" data-id="${esc(frame.id)}">
      <div class="frame-plate tone-${esc(frame.tone)}">
        <span class="frame-rule" aria-hidden="true"></span>
        <p class="frame-no">${esc(frame.no)}</p>
        <div class="frame-names">
          <p class="kicker">${esc(frame.en)}</p>
          <h2 class="frame-name">${esc(frame.zh)}</h2>
          <p class="frame-en">${esc(frame.en)}</p>
        </div>
      </div>
      <p class="frame-desc">${esc(frame.desc)}</p>
      <div class="frame-foot">
        <span class="frame-state" data-state="${state}">${stateLabel(state)}</span>
        <button class="frame-open" type="button" data-open="${esc(frame.id)}">
          翻阅详情
        </button>
      </div>
    </article>
  `;
}

function renderStrip() {
  strip.innerHTML = FRAMES.map(frameHTML).join("");
  $("#frame-total").textContent = String(FRAMES.length).padStart(2, "0");
}

function refreshStripStates() {
  for (const frame of FRAMES) {
    const el = strip.querySelector(`.frame[data-id="${frame.id}"] .frame-state`);
    if (!el) continue;
    const state = stateOf(frame);
    el.dataset.state = state;
    el.textContent = stateLabel(state);
  }
}

function factsHTML(frame) {
  const rows = (frame.facts || []).map(([label, getter]) => {
    const value = typeof getter === "function" ? getter(CONFIG) : getter;
    return `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;
  });
  return rows.join("");
}

function switchesHTML(frame) {
  return (frame.keys || [])
    .map(({ key, name, hint }) => {
      const on = Boolean(CONFIG[key]);
      return `
        <div class="switch-row">
          <div>
            <p class="switch-name">${esc(name)}</p>
            <p class="switch-hint">${esc(hint)}</p>
          </div>
          <button class="switch" type="button" role="switch"
            aria-checked="${on}" data-key="${esc(key)}">
            <span class="switch-text">${on ? "On" : "Off"}</span>
            <span class="switch-mark" aria-hidden="true"></span>
          </button>
        </div>
      `;
    })
    .join("");
}

function openSheet(id) {
  const frame = FRAMES.find((item) => item.id === id);
  if (!frame) return;
  const plate = $("#sheet-plate");
  if (plate) plate.className = `sheet-plate tone-${frame.tone}`;
  $("#sheet-no").textContent = frame.no;
  $("#sheet-title").textContent = frame.zh;
  $("#sheet-en").textContent = frame.en;
  $("#sheet-index").textContent = `${frame.no} / ${String(FRAMES.length).padStart(2, "0")}`;
  $("#sheet-desc").textContent = frame.desc;
  $("#sheet-points").innerHTML = frame.points
    .map((point) => `<li>${esc(point)}</li>`)
    .join("");
  $("#sheet-switches").innerHTML = switchesHTML(frame);
  $("#sheet-facts").innerHTML = factsHTML(frame);
  sheet.hidden = false;
  requestAnimationFrame(() => sheet.classList.add("sheet-on"));
}

function closeSheet() {
  sheet.classList.remove("sheet-on");
  setTimeout(() => {
    sheet.hidden = true;
  }, 700);
}

async function toggleKey(button, key) {
  const next = button.getAttribute("aria-checked") !== "true";
  button.setAttribute("aria-checked", String(next));
  button.setAttribute("aria-busy", "true");
  const text = button.querySelector(".switch-text");
  if (text) text.textContent = next ? "On" : "Off";
  try {
    const data = await apiPost("config/save", { values: { [key]: next } });
    CONFIG = (data && data.values) || { ...CONFIG, [key]: next };
    toast(next ? "已开启" : "已关闭");
  } catch (err) {
    button.setAttribute("aria-checked", String(!next));
    if (text) text.textContent = !next ? "On" : "Off";
    toast(bridgeMissing ? "未连接 AstrBot，请从插件拓展页打开" : "保存失败");
  } finally {
    button.removeAttribute("aria-busy");
    refreshStripStates();
  }
}

function setupGallery() {
  const counter = $("#frame-now");
  let raf = 0;
  let lastWheel = 0;
  let dragging = false;
  let dragMoved = false;
  let dragStartX = 0;
  let dragStartScroll = 0;

  const frames = () => strip.querySelectorAll(".frame");
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  const centerIndex = () => {
    const list = frames();
    if (!list.length) return 0;
    const stripRect = strip.getBoundingClientRect();
    const center = stripRect.left + stripRect.width / 2;
    let best = 0;
    let bestDist = Infinity;
    list.forEach((frame, index) => {
      const rect = frame.getBoundingClientRect();
      const dist = Math.abs(rect.left + rect.width / 2 - center);
      if (dist < bestDist) {
        bestDist = dist;
        best = index;
      }
    });
    return best;
  };

  const syncCounter = () => {
    raf = 0;
    if (!counter) return;
    counter.textContent = String(centerIndex() + 1).padStart(2, "0");
  };

  const scrollToFrame = (index) => {
    const list = frames();
    if (!list.length) return;
    const target = clamp(index, 0, list.length - 1);
    const frame = list[target];
    if (!frame) return;
    const stripRect = strip.getBoundingClientRect();
    const frameRect = frame.getBoundingClientRect();
    const left =
      strip.scrollLeft +
      (frameRect.left - stripRect.left) -
      (strip.clientWidth - frame.offsetWidth) / 2;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    strip.scrollTo({ left, behavior: reduced ? "auto" : "smooth" });
    if (counter) counter.textContent = String(target + 1).padStart(2, "0");
  };

  strip.addEventListener(
    "scroll",
    () => {
      if (!raf) raf = requestAnimationFrame(syncCounter);
    },
    { passive: true },
  );

  strip.addEventListener(
    "wheel",
    (event) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      const current = centerIndex();
      const direction = event.deltaY > 0 ? 1 : -1;
      const next = clamp(current + direction, 0, frames().length - 1);
      if (next === current) return;
      event.preventDefault();
      const now = performance.now();
      if (now - lastWheel < 420) return;
      lastWheel = now;
      scrollToFrame(next);
    },
    { passive: false },
  );

  strip.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    scrollToFrame(centerIndex() + (event.key === "ArrowRight" ? 1 : -1));
  });

  strip.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "mouse" || event.button !== 0) return;
    dragging = true;
    dragMoved = false;
    dragStartX = event.clientX;
    dragStartScroll = strip.scrollLeft;
  });

  strip.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const dx = event.clientX - dragStartX;
    if (!dragMoved && Math.abs(dx) > 6) {
      dragMoved = true;
      strip.classList.add("dragging");
    }
    if (dragMoved) strip.scrollLeft = dragStartScroll - dx;
  });

  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    strip.classList.remove("dragging");
  };
  window.addEventListener("pointerup", endDrag);
  window.addEventListener("pointercancel", endDrag);

  strip.addEventListener("click", (event) => {
    if (dragMoved && event.detail > 0) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const button = event.target.closest("[data-open]");
    if (button) openSheet(button.dataset.open);
  });

  syncCounter();
}

function setupEvents() {
  $("#sheet-close").addEventListener("click", closeSheet);
  sheet.addEventListener("click", (event) => {
    if (event.target === sheet) closeSheet();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !sheet.hidden) closeSheet();
  });
  $("#sheet-switches").addEventListener("click", (event) => {
    const button = event.target.closest(".switch");
    if (button) toggleKey(button, button.dataset.key);
  });
}

async function main() {
  renderStrip();
  setupEvents();
  requestAnimationFrame(() => document.body.classList.add("book-on"));
  try {
    const data = await apiGet("config");
    CONFIG = (data && data.values) || {};
  } catch (err) {
    bridgeMissing = true;
  }
  refreshStripStates();
  setupGallery();
}

main();
