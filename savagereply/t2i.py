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


def markdown_to_antigravity_html(text: str) -> str:
    """将 Markdown 文本转换为 1:1 像素级原汁原味 Antigravity 沉浸式 HTML。"""
    try:
        from markdown_it import MarkdownIt
        md = MarkdownIt("commonmark").enable("table").enable("strikethrough")
        content_html = md.render(text)
    except Exception:
        # 降级：基础文本换行包装
        import html
        escaped = html.escape(text).replace("\n", "<br>")
        content_html = f"<p>{escaped}</p>"

    html_template = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    background-color: #f9f9f9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif;
    color: #111827;
    padding: 28px 32px;
    width: 820px;
    -webkit-font-smoothing: antialiased;
    font-size: 15px;
    line-height: 1.7;
    word-break: break-word;
  }}
  h1, h2, h3, h4, h5, h6 {{
    color: #0f172a;
    font-weight: 700;
    line-height: 1.4;
  }}
  h1 {{
    font-size: 22px;
    margin-top: 20px;
    margin-bottom: 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid #e5e7eb;
  }}
  h1:first-child {{
    margin-top: 0;
  }}
  h2 {{
    font-size: 18px;
    margin-top: 18px;
    margin-bottom: 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid #f3f4f6;
  }}
  h2:first-child {{
    margin-top: 0;
  }}
  h3 {{
    font-size: 16px;
    margin-top: 16px;
    margin-bottom: 10px;
  }}
  p {{
    margin-bottom: 12px;
  }}
  p:last-child {{
    margin-bottom: 0;
  }}
  strong, b {{
    font-weight: 700;
    color: #0f172a;
  }}
  em, i {{
    font-style: italic;
    color: #374151;
  }}
  /* 1:1 原生 Antigravity 标红样式：浅灰微温底色 + VS Code 经典暗红字体 + 无边框 */
  code {{
    font-family: Consolas, "SF Mono", Monaco, "Courier New", monospace;
    font-size: 0.9em;
    color: #a31515;
    background-color: #efefef;
    border-radius: 3px;
    padding: 2px 5px;
    margin: 0 2px;
    vertical-align: baseline;
  }}
  /* 1:1 原生 Antigravity 引用框：纯浅灰无边线卡片，内衬透气 */
  blockquote {{
    margin: 14px 0;
    padding: 14px 20px;
    background-color: #f3f3f3;
    border: none;
    border-radius: 6px;
    color: #111827;
    font-size: 14.5px;
    line-height: 1.65;
  }}
  blockquote p {{
    margin-bottom: 6px;
  }}
  blockquote p:last-child {{
    margin-bottom: 0;
  }}
  ul, ol {{
    padding-left: 24px;
    margin: 10px 0 14px 0;
  }}
  li {{
    margin-bottom: 6px;
    line-height: 1.7;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 14px;
  }}
  th, td {{
    border: 1px solid #e5e7eb;
    padding: 9px 13px;
    text-align: left;
  }}
  th {{
    background-color: #f3f4f6;
    font-weight: 600;
    color: #1f2937;
  }}
  tr:nth-child(even) {{
    background-color: #fafafa;
  }}
  pre {{
    background: #1e1e2e;
    color: #cdd6f4;
    border-radius: 6px;
    padding: 14px 18px;
    overflow-x: auto;
    font-family: Consolas, "SF Mono", monospace;
    font-size: 13.5px;
    line-height: 1.6;
    margin: 14px 0;
  }}
  pre code {{
    color: inherit;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
  }}
  hr {{
    border: none;
    border-top: 1px solid #e5e7eb;
    margin: 20px 0;
  }}
</style>
</head>
<body>
  <div id="content">
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
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            "--window-size=820,1500",
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
            # 根据沉浸式背景色 RGB (249, 249, 249) 切除视口底部多余留白
            bg = Image.new(im.mode, im.size, (249, 249, 249))
            diff = ImageChops.difference(im, bg)
            bbox = diff.getbbox()
            if bbox:
                pad_v = 28 * 2  # 2x Retina 采样下底部保留舒适内边距
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
