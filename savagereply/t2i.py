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


def clean_markdown_for_rendering(text: str) -> str:
    """对 Markdown 进行安全的预处理，确保渲染稳定性。

    纯净原则：
    1. 严格不篡改、不破坏原文的加粗（**）、标题（#）和列表结构；
    2. 严格不粗暴乱拆反引号，保持原文语义完整性；
    3. 规范连续多余空行，保持排版呼吸感。
    """
    if not text:
        return ""

    import re

    # 折叠超过 3 行以上的连续空行，保持干净紧凑的段间距
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    return cleaned


def markdown_to_antigravity_html(text: str) -> str:
    """将 Markdown 文本转换为 1:1 像素级原汁原味 Antigravity 沉浸式气泡卡片 HTML。

    严格采纳 Antigravity 宿主原生排版与色彩系统：
    - 页面底板：--bg-page (#f0f2f5) 柔和微灰
    - 消息主体气泡：--bg-card (#ffffff) 纯白卡片，带 12px 圆角与柔和微阴影
    - 正文字体栈：优先系统现代黑体，完美覆盖 Windows / macOS / Linux (微米黑与思源黑体)
    - 行内代码：克制典雅的暗红高亮 (--code-color: #a31515, 底色 #f3f4f6, 4px 圆角)
    - 引用块：经典灰竖条 (3.5px solid #cbd5e1) + 浅灰卡片平底
    - 表格：md-table-wrapper 圆角卡片，消除边框重叠，表头 #f8fafc 浅底
    """
    cleaned_text = clean_markdown_for_rendering(text)

    try:
        from markdown_it import MarkdownIt

        md = MarkdownIt("commonmark").enable("table").enable("strikethrough")
        content_html = md.render(cleaned_text)
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
  :root {{
    --bg-page: #f0f2f5;
    --bg-card: #ffffff;
    --text-primary: #111827;
    --text-secondary: #4b5563;
    --text-muted: #6b7280;
    --border: #e5e7eb;
    --border-card: #e2e8f0;
    --code-color: #a31515;
    --code-bg: #f3f4f6;
    --table-head: #f8fafc;
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    background-color: var(--bg-page);
    padding: 24px;
    width: 820px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "WenQuanYi Micro Hei", "Noto Sans CJK SC", "Noto Sans SC", sans-serif;
    font-size: 15px;
    line-height: 1.72;
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
  }}
  .antigravity-bubble {{
    background-color: var(--bg-card);
    border: 1px solid var(--border-card);
    border-radius: 12px;
    padding: 28px 32px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
    word-break: break-word;
  }}
  h1, h2, h3, h4, h5, h6 {{
    color: #0f172a;
    font-weight: 600;
    line-height: 1.4;
    margin-top: 22px;
    margin-bottom: 10px;
  }}
  h1:first-child, h2:first-child, h3:first-child, h4:first-child {{
    margin-top: 0;
  }}
  h1 {{ font-size: 20px; }}
  h2 {{ font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  h3 {{ font-size: 16.5px; }}
  h4 {{ font-size: 15px; color: #334155; }}
  p {{
    margin-bottom: 12px;
  }}
  p:last-child {{
    margin-bottom: 0;
  }}
  strong, b {{
    font-weight: 600;
    color: #0f172a;
  }}
  em, i {{
    font-style: italic;
    color: #475569;
  }}
  /* 1:1 Antigravity 原汁原味克制高亮 */
  code {{
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    font-size: 0.88em;
    color: var(--code-color);
    background-color: var(--code-bg);
    border-radius: 4px;
    padding: 2px 6px;
    margin: 0 2px;
    white-space: pre-wrap;
    word-break: break-word;
    vertical-align: baseline;
  }}
  /* 1:1 Antigravity 引用框 */
  blockquote {{
    border-left: 3.5px solid #cbd5e1;
    background-color: #f8fafc;
    padding: 10px 16px;
    margin: 14px 0;
    border-radius: 0 6px 6px 0;
    color: #475569;
    font-size: 14px;
    line-height: 1.65;
  }}
  blockquote p {{
    margin: 4px 0;
  }}
  blockquote p:first-child {{ margin-top: 0; }}
  blockquote p:last-child {{ margin-bottom: 0; }}
  /* 列表排版：统一优雅圆点与舒适间距 */
  ul, ol {{
    padding-left: 22px;
    margin: 8px 0 14px 0;
  }}
  ul {{
    list-style-type: disc;
  }}
  ul ul {{
    list-style-type: circle;
  }}
  li {{
    margin-bottom: 5px;
    line-height: 1.7;
    color: var(--text-primary);
  }}
  li:last-child {{
    margin-bottom: 0;
  }}
  li > ul, li > ol {{
    margin: 4px 0 6px 0;
    padding-left: 20px;
  }}
  /* 表格 */
  .md-table-host {{
    margin: 16px 0;
    position: relative;
  }}
  .md-table-scroll {{
    width: 100%;
    overflow-x: auto;
  }}
  .md-table-wrapper {{
    position: relative;
    width: 100%;
    border-radius: 8px;
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
    padding: 9px 14px;
    text-align: left;
    font-weight: 600;
    line-height: 1.4;
    border: 1px solid var(--border);
    color: #1e293b;
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
            "--font-render-hinting=medium",
            "--enable-font-antialiasing",
            "--force-device-scale-factor=2",
            f"--window-size=820,{est_height}",
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
