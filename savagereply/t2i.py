"""详细输出转高质感卡片长图 (T2I: Text-to-Image)。

100% 像素级复刻 Antigravity 沉浸式原生排版规范：
- 沉浸式微暖浅灰背景 (#f9f9f9)，无多余外部浮动框与阴影，自然利落
- 现代字体栈，正文深黑 (#111827)，行高舒适，字重对比鲜明 (700 加厚)
- 行内代码/关键参数原汁原味代码高亮：浅灰微温底色 (#efefef) + VS Code 经典深暗红高亮 (#a31515)，无突兀边框
- 引用块：纯浅灰平底圆角框 (#f3f3f3)，无左侧边条竖线，内衬透气舒适
- 斑马纹现代数据表格与深色代码块
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


def smart_antigravity_format(text: str) -> str:
    """智能规范化 Markdown 文本，使其对齐 Antigravity 专业工程师排版水准。

    核心优化：
    1. 保护机制：围栏代码块（```）和表格行（|）严格原样保留，绝不下刀；
    2. 结构化序号规整：将口语化的中文序号（如 "1、先把短剧压小..."）自动升格为
       带字重加厚的小标题与缩进列表项，杜绝密密麻麻顶格挤在一起；
    3. 规范化示例引用卡片：将 "举例：" / "注意：" 等自动升格为高质感引用框卡片（> **举例**：...）；
    4. 拆解误包裹长句的反引号：将整长句反引号还原，并将内部用 " + " 或逗号连接的
       关键参数独立拆解为多个精致高亮的参数 tag，杜绝大片连贯红底。
    """
    if not text:
        return ""

    import re

    lines = text.splitlines()
    formatted_lines = []
    in_fence = False

    for line in lines:
        stripped = line.strip()

        # 保护代码块围栏
        if stripped.startswith("```"):
            in_fence = not in_fence
            formatted_lines.append(line)
            continue
        if in_fence:
            formatted_lines.append(line)
            continue

        # 保护表格行与已有标准 Markdown 列表/标题/引用
        if stripped.startswith(("|", "#", "- ", "* ", ">", "• ")):
            formatted_lines.append(line)
            continue

        if not stripped:
            formatted_lines.append("")
            continue

        # 1. 识别中文序号开头的条目，如 "1、先把短剧压小，保完成 只做60-90秒..."
        m_num = re.match(r"^([0-9]+)[、.．]\s*(.+)$", stripped)
        if m_num:
            num = m_num.group(1)
            content = m_num.group(2).strip()
            # 分离短标题与详细说明
            parts = content.split(" ", 1)
            if len(parts) == 2 and 2 <= len(parts[0]) <= 30:
                title = parts[0].strip().strip("*")
                body = parts[1].strip()
                formatted_lines.append(f"#### {num}. {title}")
                formatted_lines.append(f"- {body}")
                continue
            else:
                formatted_lines.append(f"#### {num}. {content}")
                continue

        # 2. 识别 "举例：" / "示例：" / "注意：" / "提示：" / "总结：" 并转为高质感引用框
        match_callout = re.match(r"^(举例|示例|注意|提示|总结|建议)[：:]\s*(.+)$", stripped)
        if match_callout:
            tag = match_callout.group(1)
            callout_body = match_callout.group(2).strip()
            if callout_body.startswith("`") and callout_body.endswith("`") and len(callout_body) > 10:
                callout_body = callout_body[1:-1].strip()
            formatted_lines.append(f"> **{tag}**：{callout_body}")
            continue

        formatted_lines.append(line)

    result = "\n".join(formatted_lines)

    # 3. 拆解过长的复合反引号参数串
    def _split_compound_inline_code(match: re.Match) -> str:
        code_str = match.group(1)
        # 如果包含 " + "，拆解为 `A` + `B`
        if " + " in code_str and len(code_str) > 15:
            tokens = code_str.split(" + ")
            return " + ".join(f"`{t.strip()}`" if t.strip() else "" for t in tokens)
        # 如果包含逗号分隔的多个参数英文词（如 negative 词表）且过长，独立拆解
        if ", " in code_str and len(code_str) > 35 and not any(ch in code_str for ch in "();{}"):
            tokens = code_str.split(", ")
            return ", ".join(f"`{t.strip()}`" if t.strip() else "" for t in tokens)
        # 如果反引号包裹了包含中文逗号句号的长句，解开包裹避免全句红底
        if len(code_str) > 40 and ("，" in code_str or "。" in code_str):
            return code_str
        return f"`{code_str}`"

    result = re.sub(r"`([^`\n]+)`", _split_compound_inline_code, result)
    return result


def markdown_to_antigravity_html(text: str) -> str:
    """将 Markdown 文本转换为 1:1 像素级原汁原味 Antigravity 沉浸式气泡卡片 HTML。

    严格采纳 Antigravity 宿主前端源码逆向提取的色彩体系与消息气泡设计：
    - 外层底板：--app-bg (#f3f4f6)
    - 消息主体气泡：--card-bg (#ffffff) 纯白卡片，带 14px 圆角与柔和微阴影
    - 正文字体：-apple-system / BlinkMacSystemFont / Segoe UI / PingFang SC
    - 行内代码：--code (#a31515) + 浅灰底色 (rgba(0,0,0,0.045)) + 等宽代码字体
    - 引用块：左侧 4px solid var(--border-quote) + 浅灰底色 + 圆角卡片
    - 表格：md-table-wrapper 圆角卡片包裹，消除边框重叠，表头 var(--secondary) 浅灰底
    """
    # 先行通过 Antigravity 排版智能美化器
    enhanced_text = smart_antigravity_format(text)

    try:
        from markdown_it import MarkdownIt

        md = MarkdownIt("commonmark").enable("table").enable("strikethrough")
        content_html = md.render(enhanced_text)
    except Exception:
        # 降级：基础文本换行包装
        import html

        escaped = html.escape(enhanced_text).replace("\n", "<br>")
        content_html = f"<p>{escaped}</p>"

    # 1:1 原生 Antigravity 表格结构：自动包裹三层外层容器，实现圆角无溢出裁切与边框重叠消除
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
  :root {{
    --app-bg: #f3f4f6;
    --card-bg: #ffffff;
    --foreground: #1e2329;
    --heading: #0f141c;
    --secondary: #f4f5f7;
    --muted: #f7f8fa;
    --border: rgba(0, 0, 0, 0.08);
    --border-quote: #d0d7de;
    --code: #a31515;
    --code-bg: rgba(0, 0, 0, 0.045);
    --radius-card: 14px;
    --radius-sm: 6px;
    --radius-lg: 8px;
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    background-color: var(--app-bg);
    padding: 24px;
    width: 860px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
  }}
  /* 1:1 原生 Antigravity 消息卡片气泡 */
  .antigravity-bubble {{
    background-color: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.035), 0 1px 3px rgba(0, 0, 0, 0.02);
    padding: 26px 30px;
    color: var(--foreground);
    font-size: 14.5px;
    line-height: 1.7;
    word-break: break-word;
  }}
  h1, h2, h3, h4, h5, h6 {{
    color: var(--heading);
    font-weight: 600;
    line-height: 1.4;
  }}
  h1 {{ font-size: 20px; margin: 20px 0 12px 0; }}
  h2 {{ font-size: 18px; margin: 18px 0 10px 0; }}
  h3 {{ font-size: 16px; margin: 16px 0 8px 0; }}
  h4 {{
    font-size: 15.5px;
    margin: 16px 0 8px 0;
    color: var(--heading);
    letter-spacing: -0.01em;
  }}
  h1:first-child, h2:first-child, h3:first-child, h4:first-child {{
    margin-top: 0;
  }}
  p {{
    margin-bottom: 12px;
  }}
  p:last-child {{
    margin-bottom: 0;
  }}
  strong, b {{
    font-weight: 600;
    color: var(--heading);
  }}
  em, i {{
    font-style: italic;
    color: #374151;
  }}
  /* 1:1 原生 Antigravity 标红样式：VS Code 经典深暗红字体 + 浅灰透明底色 + 等宽字体 */
  code {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    font-size: 0.88em;
    color: var(--code);
    background-color: var(--code-bg);
    border-radius: 4px;
    padding: 2px 6px;
    margin: 0 2px;
    white-space: pre-wrap;
    word-break: break-word;
    vertical-align: baseline;
  }}
  /* 1:1 原生 Antigravity 引用框：左侧 4px solid 竖条 + 浅灰卡片底色 */
  blockquote {{
    border-left: 4px solid var(--border-quote);
    background-color: var(--muted);
    padding: 10px 16px;
    margin: 12px 0;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    color: #4b5563;
    font-size: 14px;
    line-height: 1.65;
  }}
  blockquote p {{
    margin: 4px 0;
  }}
  blockquote p:first-child {{
    margin-top: 0;
  }}
  blockquote p:last-child {{
    margin-bottom: 0;
  }}
  /* 列表层级与圆点 */
  ul, ol {{
    padding-left: 22px;
    margin: 8px 0 14px 0;
  }}
  li {{
    margin-bottom: 6px;
    line-height: 1.68;
    color: var(--foreground);
  }}
  li:last-child {{
    margin-bottom: 0;
  }}
  li > ul, li > ol {{
    margin: 4px 0;
  }}
  /* 1:1 原生 Antigravity Markdown 表格规范：圆角容器 + 消除双边框 + 柔和表头 */
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
    border-radius: var(--radius-lg);
    overflow: hidden;
    border: 1px solid var(--border);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
  }}
  .md-table-wrapper table {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 13.5px;
    background-color: #ffffff;
  }}
  .md-table-wrapper th {{
    background-color: var(--secondary);
    padding: 8px 12px;
    text-align: left;
    font-weight: 600;
    font-size: 13px;
    line-height: 1.375;
    border: 1px solid var(--border);
    color: var(--heading);
  }}
  .md-table-wrapper td {{
    padding: 8px 12px;
    line-height: 1.5;
    font-size: 13px;
    border: 1px solid var(--border);
    color: #1a1a1a;
    background-color: #ffffff;
  }}
  /* 官方消除外侧重叠边框 */
  .md-table-wrapper thead tr:first-child th {{
    border-top: 0;
  }}
  .md-table-wrapper tbody tr:last-child td {{
    border-bottom: 0;
  }}
  .md-table-wrapper th:first-child,
  .md-table-wrapper td:first-child {{
    border-left: 0;
  }}
  .md-table-wrapper th:last-child,
  .md-table-wrapper td:last-child {{
    border-right: 0;
  }}
  /* 代码块 */
  pre {{
    background-color: #1e1e2e;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 12px 16px;
    margin: 12px 0;
    overflow-x: auto;
  }}
  pre code {{
    color: #cdd6f4;
    background-color: transparent;
    padding: 0;
    margin: 0;
    border-radius: 0;
    font-size: 13px;
    line-height: 1.55;
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
            "--force-device-scale-factor=2",
            f"--window-size=860,{est_height}",
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
                pad_v = 20 * 2  # 2x Retina 采样下底部保留 20px 对称外边距
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
