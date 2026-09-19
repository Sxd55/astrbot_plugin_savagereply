"""详细输出转高质感卡片长图 (T2I: Text-to-Image)。

100% 像素级复刻 Antigravity 沉浸式原生排版规范：
- 极简纯净纯色页面 (#ffffff)，无多余外部浮动框与阴影，自然利落
- 现代字体栈，优先 Segoe UI / 微软雅黑 (Windows) 与苹方 (macOS)，思源黑体作为纯服务器无缝兜底
- 正文深灰黑 (#1f2328)，行高 1.62，黑色加粗 (#1f2328, 600) 为核心视觉锚点
- 行内代码极度克制：浅灰微温底色 (#f6f8fa) + VS Code 经典深暗红高亮 (#a31515)，无突兀边框
- 次级列表深度缩进 (22px)，阶梯式呈现清晰架构
- 引用块：纯浅灰平底圆角框 (#f8fafc)，左侧浅灰蓝竖线，内衬透气舒适
- 高清 2x Retina 采样与自适应无损纵向裁切

系统依赖：
优先调用系统自带的 Chromium 内核无头浏览器（Windows Edge / Google Chrome 等），
配合 Pillow 自动计算内容区域切除多余空白，零大型外部框架依赖，秒级渲染。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ReplyOptions

_CACHED_BROWSER_PATH: str | None = None
_BROWSER_SEARCHED: bool = False


def find_browser_executable() -> str | None:
    """探测系统可用的 Chromium 内核浏览器可执行文件路径。"""
    global _CACHED_BROWSER_PATH, _BROWSER_SEARCHED
    if _BROWSER_SEARCHED:
        return _CACHED_BROWSER_PATH

    _BROWSER_SEARCHED = True

    # 1. 显式环境变量优先
    for env in ("SAVAGE_BROWSER_PATH", "EDGE_PATH", "CHROME_PATH"):
        val = os.environ.get(env)
        if val and os.path.isfile(val):
            _CACHED_BROWSER_PATH = val
            return _CACHED_BROWSER_PATH

    # 2. Windows 常见安装位置
    win_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in win_candidates:
        if os.path.isfile(candidate):
            _CACHED_BROWSER_PATH = candidate
            return _CACHED_BROWSER_PATH

    # 3. PATH 环境变量搜索
    names = (
        "msedge",
        "microsoft-edge",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    )
    for name in names:
        w = shutil.which(name)
        if w and os.path.isfile(w):
            _CACHED_BROWSER_PATH = w
            return _CACHED_BROWSER_PATH

    # 4. Linux 常见二进制路径
    linux_candidates = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
        "/snap/bin/chromium",
        "/usr/local/bin/chromium",
        "/usr/local/bin/chrome",
    ]
    for candidate in linux_candidates:
        if os.path.isfile(candidate):
            _CACHED_BROWSER_PATH = candidate
            return _CACHED_BROWSER_PATH

    # 5. macOS 常见位置
    mac_candidates = [
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for mac_path in mac_candidates:
        if os.path.isfile(mac_path):
            _CACHED_BROWSER_PATH = mac_path
            return _CACHED_BROWSER_PATH

    return None


def clean_markdown_for_rendering(text: str) -> str:
    """对 Markdown 进行结构规范化与智能安全高亮增强，确保 1:1 原汁原味呈现 Antigravity 红色标红效果。

    安全增强原则：
    1. 保护现有语法：围栏代码块、已有反引号、表格线、链接与 HTML 标签严禁二次破坏；
    2. 自动修正表格空行：确保 CommonMark 解析器能 100% 正确解析 Markdown 表格；
    3. 智能关键词高亮补偿：自动识别命令行参数（--seed, --ar 16:9）、AI生图与技术核心参数（seed, negative, prompt, 720p）、
       参数词串（如 negative 后的英文提示词）以及脚本文件（policy.py），自动赋予反引号包裹，使其精准呈现 Antigravity 官方暗红高亮；
    4. 折叠异常连续空行，保持干净紧凑的呼吸感排版。
    """
    if not text:
        return ""

    import re

    # 0. 智能层级规范化与导引词加粗：
    # 0.1 次级列表智能缩进对齐：编号项后面的 - 或 • 自动缩进 4 格
    # 0.2 列表导引词自动加粗：当列表项（如 - 闲聊直接回：）冒号前的短语未加粗时，自动赋予 **加粗**，100% 呈现 Antigravity 黑白对比架构感
    lines = text.split("\n")
    sublist_processed = []
    in_num_item = False
    for line in lines:
        stripped = line.strip()
        # 匹配一级编号小项：如 "1. 意图判定："
        num_m = re.match(r"^(\d+\.\s+)(?!\*\*)([^\n:*`]{2,14})([:：])(.*)$", stripped)
        if num_m:
            in_num_item = True
            pfx, term, col, rest = num_m.groups()
            sublist_processed.append(f"{pfx}**{term.strip()}**{col}{rest}")
            continue
        if re.match(r"^\d+\.\s+", stripped):
            in_num_item = True
            sublist_processed.append(line)
            continue

        # 次级列表项处理
        if in_num_item and re.match(r"^[•\-\*]\s+", stripped):
            content = re.sub(r"^[•\-\*]\s*", "- ", stripped)
            # 自动加粗未加粗的导引词（如 "- 闲聊直接回：" -> "    - **闲聊直接回**："）
            sub_m = re.match(r"^(- \s*)(?!\*\*)([^\n:*`]{2,14})([:：])(.*)$", content)
            if sub_m:
                spfx, sterm, scol, srest = sub_m.groups()
                content = f"{spfx}**{sterm.strip()}**{scol}{srest}"
            sublist_processed.append("    " + content)
            continue
        elif re.match(r"^[•\-\*]\s+", stripped):
            content = re.sub(r"^[•\-\*]\s*", "- ", stripped)
            sub_m = re.match(r"^(- \s*)(?!\*\*)([^\n:*`]{2,14})([:：])(.*)$", content)
            if sub_m:
                spfx, sterm, scol, srest = sub_m.groups()
                content = f"{spfx}**{sterm.strip()}**{scol}{srest}"
            sublist_processed.append(content)
            continue

        if not stripped or stripped.startswith("#"):
            in_num_item = False
        sublist_processed.append(line)
    text = "\n".join(sublist_processed)

    # 1. 占位保护已有语法结构（围栏代码块必须最先保护）
    placeholders = []

    def save_placeholder(m):
        idx = len(placeholders)
        placeholders.append(m.group(0))
        return f"@@PROTECTED_{idx}@@"

    # 保护围栏代码块
    text = re.sub(r"```[\s\S]*?```", save_placeholder, text)

    # 2. 严格按成对反引号解析行内代码，仅对真正滥用反引号的纯中文长句（>=5汉字）优雅降级为加粗
    # 彻底杜绝全局正则跨代码块配对（将闭合反引号与下一起始反引号误判为一对）的灾难
    lines = text.split("\n")
    processed_lines = []
    for line in lines:
        parts = line.split("`")
        if len(parts) >= 3:
            new_parts = []
            for i, part in enumerate(parts):
                if i % 2 == 1:
                    # 真正的成对行内代码内部
                    chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", part))
                    # 包含 5 个以上汉字，且不是包含常见运算符的技术表达式时才降级为加粗
                    if chinese_chars >= 5 and not any(op in part for op in ["+", "-", "*", "/", "=", "--"]):
                        new_parts.append(f"**{part}**")
                    else:
                        new_parts.append(f"`{part}`")
                else:
                    new_parts.append(part)
            processed_lines.append("".join(new_parts))
        else:
            processed_lines.append(line)
    text = "\n".join(processed_lines)

    # 3. 规范表格前后的空行，避免 CommonMark 将紧跟段落的表格误判为普通文本
    text = re.sub(r"([^\n])\n(\|[^\n]+\|\s*\n\|[-: |]+\|)", r"\1\n\n\2", text)
    text = re.sub(r"(\|[^\n]+\|\s*)\n([^\n|])", r"\1\n\n\2", text)

    # 4. 占位保护已有的合法行内反引号、表格线、链接与 HTML
    protected = re.sub(r"`[^`\n]+`", save_placeholder, text)
    # 保护表格分隔行 (| --- | :---: |)，防止短横线被命令行参数规则误匹配
    protected = re.sub(r"\|(?:\s*:?-+:?\s*\|)+", save_placeholder, protected)
    # 保护 Markdown 链接与图片
    protected = re.sub(r"!?\[.*?\]\(.*?\)", save_placeholder, protected)
    # 保护 HTML 标签
    protected = re.sub(r"<[^>]+>", save_placeholder, protected)

    # 5. 精准克制的高亮匹配（对齐 Antigravity 原生风格，严禁泛滥）

    # 5.1 引用块内的提示/举例前缀美化（> 提示： -> > **提示**：）
    protected = re.sub(
        r"(^> *(?:提示|举例|注意|说明|技巧|警告|参考)[:：])",
        lambda m: f"> **{m.group(1).lstrip('> *').rstrip(':：')}**：",
        protected,
        flags=re.MULTILINE,
    )

    # 5.2 命令行参数与选项 (--seed 12345, --ar 16:9, -v) 首字符必须是字母
    protected = re.sub(
        r"(?<![a-zA-Z0-9`])(--[a-zA-Z][a-zA-Z0-9_-]*(?:\s+[a-zA-Z0-9_.:/-]+)?)(?![a-zA-Z0-9`])",
        r"`\1`",
        protected,
    )

    # 5.3 常见脚本与配置文件名 (tests/test_t2i.py, config.json, main.py 等)
    protected = re.sub(
        r"(?<![a-zA-Z0-9`/])([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+\.(?:py|json|yaml|yml|js|ts|sh|bat|md|css|html))(?![a-zA-Z0-9`])",
        r"`\1`",
        protected,
        flags=re.IGNORECASE,
    )

    # 4. 还原占位保护结构
    for i, orig in enumerate(placeholders):
        protected = protected.replace(f"@@PROTECTED_{i}@@", orig)
    # 5. 规范化 Markdown 加粗标记，彻底修复 LLM 常见的星号粘连、空格错位与标点边界冲突
    # 5.1 连续 4 个以上星号拆开为 ** **
    protected = re.sub(r"\*{4,}", "** **", protected)
    # 5.2 修复 ** 紧贴在代码块或反引号边缘且没有空格隔开：`code`**text** -> `code` **text**
    protected = re.sub(r"(`)\*\*([^\s*])", r"\1 **\2", protected)
    protected = re.sub(r"([^\s*])\*\*(`)", r"\1** \2", protected)
    # 5.3 修复星号内侧的多余空格（CommonMark 规范禁止星号内侧有空格）：** text ** -> **text**
    protected = re.sub(r"\*\*\s+([^\*\n]+?)\s+\*\*", r"**\1**", protected)
    protected = re.sub(r"\*\*\s+([^\*\n]+?)\*\*", r"**\1**", protected)
    protected = re.sub(r"\*\*([^\*\n]+?)\s+\*\*", r"**\1**", protected)

    # 6. 折叠超过 3 行以上的连续空行，保持排版呼吸感
    cleaned = re.sub(r"\n{3,}", "\n\n", protected.strip())
    return cleaned


def _ensure_linux_font_installed() -> None:
    """在 Linux 系统下，自动将插件内置的思源黑体安装/软链接至用户字体目录，
    确保无头 Chromium 能 100% 原生识别并使用顶级思源黑体，完全免除用户手动配置。
    """
    import platform
    if platform.system() != "Linux":
        return

    try:
        font_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
        ttf_file = font_dir / "NotoSansSC-VF.ttf"
        if not ttf_file.exists():
            return

        user_font_dir = Path.home() / ".local" / "share" / "fonts"
        user_font_dir.mkdir(parents=True, exist_ok=True)
        target = user_font_dir / "NotoSansSC-VF.ttf"

        if not target.exists():
            import shutil
            shutil.copy2(str(ttf_file), str(target))
            # 刷新系统字体缓存
            import subprocess
            subprocess.run(["fc-cache", "-f", str(user_font_dir)], capture_output=True, timeout=5)
    except Exception:
        pass


def _get_builtin_font_face_css() -> str:
    """自动检测插件目录内置字体（如思源黑体 Noto Sans SC），生成 @font-face CSS。"""
    _ensure_linux_font_installed()
    try:
        font_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
        if not font_dir.exists():
            return ""
        for ext, fmt in [(".woff2", "woff2"), (".ttf", "truetype"), (".otf", "opentype")]:
            for font_file in font_dir.glob(f"*{ext}"):
                uri = font_file.resolve().as_uri()
                return f"""
@font-face {{
  font-family: 'AntigravitySans';
  src: url('{uri}') format('{fmt}');
  font-weight: 100 900;
  font-style: normal;
  font-display: swap;
}}
"""
    except Exception:
        pass
    return ""


def markdown_to_antigravity_html(text: str) -> str:
    """将 Markdown 文本转换为 1:1 像素级原汁原味 Antigravity 沉浸式纯色卡片 HTML。

    严格采纳 Antigravity 宿主原生排版与色彩系统：
    - 页面底板：纯白 (#ffffff)，无多余外部浮动框与阴影，自然利落
    - 正文字体栈：Windows 优先微软雅黑与 Segoe UI，macOS 优先苹方，内置思源黑体兜底
    - 黑色加粗：作为视觉核心锚点 (#1f2328, 600 字重)
    - 行内代码：极度克制深暗红高亮 (--code-color: #a31515, 底色 #f6f8fa, 3px 圆角)
    - 次级列表：深度缩进 (22px)，完美呈现阶梯层级排版
    - 引用块：经典灰竖条 (3px solid #cbd5e1) + 极浅平底
    - 表格：md-table-wrapper 圆角卡片，消除边框重叠，表头 #f8fafc 浅底
    """
    cleaned_text = clean_markdown_for_rendering(text)
    builtin_font_css = _get_builtin_font_face_css()

    try:
        from markdown_it import MarkdownIt

        md = MarkdownIt("commonmark").enable("table").enable("strikethrough")
        content_html = md.render(cleaned_text)
    except Exception:
        try:
            import markdown

            content_html = markdown.markdown(
                cleaned_text,
                extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
            )
        except Exception:
            import html

            escaped = html.escape(cleaned_text).replace("\n", "<br>")
            content_html = f"<p>{escaped}</p>"

    # 1:1 原生 Antigravity 表格结构：自动包裹外层容器，实现圆角无溢出裁切与边框重叠消除
    import re

    content_html = re.sub(
        r"(<table\b[^>]*>[\s\S]*?</table>)",
        r'<div class="md-table-host"><div class="md-table-scroll"><div class="md-table-wrapper">\1</div></div></div>',
        content_html,
    )

    html_template = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
{builtin_font_css}
  :root {{
    --bg-page: #ffffff;
    --text-primary: #1f2328;
    --text-secondary: #475569;
    --text-muted: #6b7280;
    --border: #e1e4e8;
    --code-color: #a31515;
    --code-bg: #f6f8fa;
    --table-head: #f8fafc;
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    background-color: var(--bg-page);
    padding: 24px 28px;
    width: 800px;
    font-family: 'AntigravitySans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    font-size: 14.2px;
    font-weight: 450;
    line-height: 1.68;
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
  }}
  .antigravity-bubble {{
    background-color: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
    box-shadow: none;
    word-break: break-word;
  }}
  h1, h2, h3, h4, h5, h6 {{
    color: #111827;
    font-weight: 700;
    line-height: 1.4;
    margin-top: 18px;
    margin-bottom: 8px;
  }}
  h1:first-child, h2:first-child, h3:first-child, h4:first-child {{
    margin-top: 0;
  }}
  h1 {{ font-size: 19px; }}
  h2 {{ font-size: 17px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  h3 {{ font-size: 15.5px; }}
  h4 {{ font-size: 14.2px; color: #1e293b; }}
  p {{
    margin-bottom: 10px;
  }}
  p:last-child {{
    margin-bottom: 0;
  }}
  strong, b {{
    font-weight: 700;
    color: #111827;
  }}
  em, i {{
    font-style: italic;
    color: #475569;
  }}
  /* 1:1 像素级精准 Antigravity 标红高亮 */
  code {{
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    font-size: 0.88em;
    color: var(--code-color);
    background-color: var(--code-bg);
    border-radius: 3px;
    padding: 1.5px 5px;
    margin: 0 2px;
    white-space: pre-wrap;
    word-break: break-word;
    vertical-align: baseline;
  }}
  /* 1:1 Antigravity 优雅微灰引用框 */
  blockquote {{
    border-left: 3px solid #cbd5e1;
    background-color: #f8fafc;
    padding: 10px 16px;
    margin: 12px 0;
    border-radius: 4px;
    color: #374151;
    font-size: 13.8px;
    line-height: 1.62;
  }}
  blockquote p {{
    margin: 4px 0;
  }}
  blockquote p:first-child {{ margin-top: 0; }}
  blockquote p:last-child {{ margin-bottom: 0; }}
  /* 列表排版：对齐图2/图3的次级列表明显缩进与圆点呼吸感 */
  ul, ol {{
    padding-left: 24px;
    margin: 6px 0 10px 0;
  }}
  ul {{
    list-style-type: disc;
  }}
  ul ul {{
    list-style-type: circle;
  }}
  li {{
    margin-bottom: 5px;
    line-height: 1.62;
    color: var(--text-primary);
  }}
  li::marker {{
    color: #374151;
  }}
  li:last-child {{
    margin-bottom: 0;
  }}
  /* 嵌套次级列表：深度缩进呈现层级阶梯感（1:1 复刻图3） */
  li > ul, li > ol {{
    margin: 4px 0 6px 0;
    padding-left: 22px;
  }}
  li > p {{
    margin-bottom: 4px;
  }}
  /* 表格 */
  .md-table-host {{
    margin: 14px 0;
    position: relative;
  }}
  .md-table-scroll {{
    width: 100%;
    overflow-x: auto;
  }}
  .md-table-wrapper {{
    position: relative;
    width: 100%;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid var(--border);
  }}
  .md-table-wrapper table {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 13.5px;
    background-color: #ffffff;
  }}
  .md-table-wrapper th {{
    background-color: var(--table-head);
    padding: 8px 12px;
    text-align: left;
    font-weight: 700;
    line-height: 1.4;
    border: 1px solid var(--border);
    color: #101010;
  }}
  .md-table-wrapper td {{
    padding: 9px 14px;
    line-height: 1.55;
    border: 1px solid var(--border);
    color: #334155;
    background-color: #ffffff;
  }}
  .md-table-wrapper thead tr:first-child th {{ border-top: 0; }}
  .md-table-wrapper tbody tr:last-child td {{ border-bottom: 0; }}
  .md-table-wrapper th:first-child, .md-table-wrapper td:first-child {{ border-left: 0; }}
  .md-table-wrapper th:last-child, .md-table-wrapper td:last-child {{ border-right: 0; }}
  /* 代码块 */
  pre {{
    background-color: #0f172a;
    border-radius: 8px;
    padding: 14px 18px;
    margin: 14px 0;
    overflow-x: auto;
  }}
  pre code {{
    color: #e2e8f0;
    background-color: transparent;
    padding: 0;
    margin: 0;
    border-radius: 0;
    font-size: 13px;
    line-height: 1.6;
    white-space: pre;
  }}
  hr {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 18px 0;
  }}
</style>
</head>
<body>
  <div class="antigravity-bubble">
    {content_html}
  </div>
</body>
</html>
"""
    return html_template


def _get_image_cache_dir() -> Path:
    # 优先使用插件内部数据目录或家目录，避免 Linux Snap / AppArmor 对 /tmp 的沙箱隔离
    base_dir = Path(__file__).resolve().parent.parent / "data" / "t2i_cache"
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir
    except Exception:
        fallback = Path.home() / ".astrbot_t2i_cache"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def render_markdown_to_image_sync(
    text: str,
    output_path: str | None = None,
    timeout_seconds: float = 8.0,
) -> str | None:
    """同步将 Markdown 渲染为图片。返回生成的 PNG 文件绝对路径；若失败返回 None。"""
    browser = find_browser_executable()
    if not browser:
        return None

    from PIL import Image, ImageChops

    html_content = markdown_to_antigravity_html(text)
    cache_dir = _get_image_cache_dir()
    file_id = uuid.uuid4().hex[:12]
    tmp_html_file = cache_dir / f"render_{file_id}.html"
    tmp_html_path = str(tmp_html_file.resolve())
    tmp_html_file.write_text(html_content, encoding="utf-8")

    tmp_shot = str((cache_dir / f"shot_{file_id}.png").resolve())
    if not output_path:
        out_file = cache_dir / f"card_{file_id}.png"
        output_path = str(out_file.resolve())

    try:
        # 根据文本长度动态估算视口高度，确保超长表格或长篇数据报告不被视口截断
        est_height = max(2000, min(8000, int(len(text) * 3.8) + 1200))
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            "--disable-web-security",
            "--allow-running-insecure-content",
            "--font-render-hinting=medium",
            "--enable-font-antialiasing",
            "--force-device-scale-factor=2",
            f"--window-size=800,{est_height}",
            f"--screenshot={tmp_shot}",
            Path(tmp_html_path).resolve().as_uri(),
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_seconds,
        )
        if res.returncode != 0:
            err_msg = (res.stderr or b"").decode(errors="ignore").strip()
            out_msg = (res.stdout or b"").decode(errors="ignore").strip()
            try:
                from astrbot.api import logger

                logger.warning(
                    "Savage's Reply: 浏览器截图命令失败 (exitcode=%s, browser=%s): %s %s",
                    res.returncode,
                    browser,
                    err_msg[:300],
                    out_msg[:300],
                )
            except Exception:
                pass
            return None

        if not os.path.exists(tmp_shot):
            try:
                from astrbot.api import logger

                logger.warning("Savage's Reply: 截图目标文件未产生: %s", tmp_shot)
            except Exception:
                pass
            return None

        with Image.open(tmp_shot) as im:
            # 动态根据画布背景色切除视口底部多余留白
            corner_color = im.getpixel((0, 0))
            bg = Image.new(im.mode, im.size, corner_color)
            diff = ImageChops.difference(im, bg)
            bbox = diff.getbbox()
            if bbox:
                pad_v = 24 * 2  # 2x Retina 采样下底部保留 24px 对称内边距（与顶部 24px 严格对称）
                bottom = min(im.height, bbox[3] + pad_v)
                cropped = im.crop((0, 0, im.width, bottom))
                cropped.save(output_path, "PNG")
            else:
                im.save(output_path, "PNG")
        return output_path
    except Exception as exc:
        try:
            from astrbot.api import logger
            logger.warning("Savage's Reply: 渲染长图捕获到异常: %s", exc)
        except Exception:
            pass
        return None
    finally:
        try:
            if os.path.exists(tmp_html_path):
                os.remove(tmp_html_path)
        except OSError:
            pass
        try:
            if os.path.exists(tmp_shot):
                os.remove(tmp_shot)
        except OSError:
            pass


async def render_markdown_to_image(
    text: str,
    output_path: str | None = None,
    timeout_seconds: float = 8.0,
) -> str | None:
    """异步将 Markdown 文本渲染为图片。在线程池中运行以防阻塞事件循环。"""
    return await asyncio.to_thread(
        render_markdown_to_image_sync,
        text,
        output_path,
        timeout_seconds,
    )


_WARNED_NO_BROWSER: bool = False


def should_render_as_image(
    text: str,
    options: ReplyOptions,
    decision_reason: str = "",
) -> bool:
    """判断当前回复是否属于详细输出，应当走图片长图回复。"""
    global _WARNED_NO_BROWSER
    if not getattr(options, "t2i_detailed_reply_enabled", True):
        return False

    is_detailed = (decision_reason in {"structured_data", "table"}) or (
        len(text.strip()) >= getattr(options, "t2i_min_chars", 200)
    )
    if not is_detailed:
        return False

    # 必须系统存在可用浏览器
    browser = find_browser_executable()
    if not browser:
        if not _WARNED_NO_BROWSER:
            _WARNED_NO_BROWSER = True
            try:
                from astrbot.api import logger
                logger.info(
                    "Savage's Reply: 触发详细回复/表格转长图，但当前系统尚未安装 Chromium 浏览器，已降级为纯文本回复。"
                    "Linux 服务器执行 'apt install -y chromium-browser fonts-wqy-microhei' 即可开启 1:1 Antigravity 卡片长图。"
                )
            except Exception:
                pass
        return False

    return True
