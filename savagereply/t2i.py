"""详细输出转高质感卡片长图 (T2I: Text-to-Image)。

复刻 Antigravity 现代排版视觉规范：
- 现代无衬线字体栈与舒适行高
- 标题层级分明与粗体加厚
- 行内代码/关键参数浅粉底色+暗红高亮 (#c7254e)
- 引用块左侧边条与灰色背景
- 斑马纹精致数据表格
- 深色现代代码块
- 卡片圆角、柔和外衬、微投影与精致页脚

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
from typing import TYPE_CHECKING, Any

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

    # 4. macOS 常见位置
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
    """将 Markdown 文本转换为具有 Antigravity 视觉风格的高清卡片 HTML。"""
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
    background-color: #f1f5f9;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    color: #1e293b;
    padding: 24px;
    display: flex;
    justify-content: center;
    -webkit-font-smoothing: antialiased;
  }}
  .card {{
    background: #ffffff;
    width: 760px;
    border-radius: 12px;
    box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05), 0 2px 6px -1px rgba(0, 0, 0, 0.03);
    border: 1px solid #e2e8f0;
    overflow: hidden;
  }}
  .card-body {{
    padding: 32px 36px;
    font-size: 15px;
    line-height: 1.75;
    word-break: break-word;
  }}
  h1, h2, h3, h4, h5, h6 {{
    color: #0f172a;
    font-weight: 650;
    line-height: 1.4;
  }}
  h1 {{
    font-size: 22px;
    margin-top: 20px;
    margin-bottom: 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid #e2e8f0;
  }}
  h1:first-child {{
    margin-top: 0;
  }}
  h2 {{
    font-size: 18px;
    margin-top: 18px;
    margin-bottom: 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid #f1f5f9;
  }}
  h2:first-child {{
    margin-top: 0;
  }}
  h3 {{
    font-size: 16px;
    margin-top: 14px;
    margin-bottom: 8px;
  }}
  p {{
    margin-bottom: 12px;
  }}
  p:last-child {{
    margin-bottom: 0;
  }}
  strong, b {{
    font-weight: 650;
    color: #0f172a;
  }}
  em, i {{
    font-style: italic;
    color: #334155;
  }}
  /* 关键词/行内代码粉底标红样式 - 100% 像素级复刻 Antigravity 视觉 */
  code {{
    font-family: "JetBrains Mono", Consolas, "Courier New", monospace;
    font-size: 0.9em;
    color: #c7254e;
    background-color: #fbf0f2;
    border: 1px solid rgba(199, 37, 78, 0.12);
    border-radius: 4px;
    padding: 2px 6px;
    margin: 0 2px;
    vertical-align: baseline;
  }}
  blockquote {{
    margin: 14px 0;
    padding: 12px 18px;
    background: #f8fafc;
    border-left: 4px solid #94a3b8;
    border-radius: 0 6px 6px 0;
    color: #475569;
    font-size: 14.5px;
  }}
  blockquote p {{
    margin-bottom: 6px;
  }}
  blockquote p:last-child {{
    margin-bottom: 0;
  }}
  ul, ol {{
    padding-left: 22px;
    margin: 10px 0 14px 0;
  }}
  li {{
    margin-bottom: 6px;
    line-height: 1.7;
  }}
  li::marker {{
    color: #64748b;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 14px;
  }}
  th, td {{
    border: 1px solid #e2e8f0;
    padding: 9px 13px;
    text-align: left;
  }}
  th {{
    background-color: #f8fafc;
    font-weight: 600;
    color: #334155;
  }}
  tr:nth-child(even) {{
    background-color: #fbfcfe;
  }}
  pre {{
    background: #1e1e2e;
    color: #cdd6f4;
    border-radius: 8px;
    padding: 14px 18px;
    overflow-x: auto;
    font-family: "JetBrains Mono", Consolas, monospace;
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
    border-top: 1px solid #e2e8f0;
    margin: 20px 0;
  }}
  .card-footer {{
    background: #fafafa;
    border-top: 1px solid #f1f5f9;
    padding: 10px 36px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 12px;
    color: #94a3b8;
  }}
  .card-footer .tag {{
    font-weight: 500;
    color: #64748b;
  }}
</style>
</head>
<body>
  <div class="card" id="render-target">
    <div class="card-body">
      {content_html}
    </div>
    <div class="card-footer">
      <span class="tag">✨ Savage's Reply</span>
      <span>Antigravity Card Engine</span>
    </div>
  </div>
</body>
</html>
"""
    return html_template


def _get_image_cache_dir() -> Path:
    cache_dir = Path(tempfile.gettempdir()) / "savagereply_images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


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
    tmp_html = tempfile.NamedTemporaryFile(
        suffix=".html",
        delete=False,
        mode="w",
        encoding="utf-8",
    )
    tmp_html_path = tmp_html.name
    tmp_html.write(html_content)
    tmp_html.close()

    tmp_shot = tmp_html_path + ".shot.png"
    if not output_path:
        out_file = _get_image_cache_dir() / f"card_{uuid.uuid4().hex[:12]}.png"
        output_path = str(out_file.resolve())

    try:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--force-device-scale-factor=2",
            "--window-size=820,1200",
            f"--screenshot={tmp_shot}",
            f"file:///{Path(tmp_html_path).as_posix()}",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_seconds,
        )
        if res.returncode != 0 or not os.path.exists(tmp_shot):
            return None

        with Image.open(tmp_shot) as im:
            # 找到卡片边界（根据外层背景色 RGB (241, 245, 249) 切除多余空白）
            bg = Image.new(im.mode, im.size, (241, 245, 249))
            diff = ImageChops.difference(im, bg)
            bbox = diff.getbbox()
            if bbox:
                pad = 16 * 2  # 2x Retina 采样下四周保留外边距
                left = max(0, bbox[0] - pad)
                top = max(0, bbox[1] - pad)
                right = min(im.width, bbox[2] + pad)
                bottom = min(im.height, bbox[3] + pad)
                cropped = im.crop((left, top, right, bottom))
                cropped.save(output_path, "PNG")
            else:
                im.save(output_path, "PNG")
        return output_path
    except Exception:
        return None
    finally:
        try:
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


def should_render_as_image(
    text: str,
    options: ReplyOptions,
    decision_reason: str = "",
) -> bool:
    """判断当前回复是否属于详细输出，应当走图片长图回复。"""
    if not getattr(options, "t2i_detailed_reply_enabled", True):
        return False

    # 必须系统存在可用浏览器
    if not find_browser_executable():
        return False

    # 1. 明确的表格或结构化多点数据分析
    if decision_reason in {"structured_data", "table"}:
        return True

    # 2. 回复长度达到配置的门槛（默认 200 字）
    min_chars = getattr(options, "t2i_min_chars", 200)
    if len(text.strip()) >= min_chars:
        return True

    return False
