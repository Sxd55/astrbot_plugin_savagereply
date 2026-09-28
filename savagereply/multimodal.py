"""多模态视觉增强：引用图片视觉输入补齐与带问题上下文的智能图像转述。"""

from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any


QUOTED_IMAGE_NOTICE = "当前消息引用了 {count} 张图片，已作为本轮视觉输入提供。"
QUOTE_IMAGE_CAPTION_BASE_PROMPT = "Please describe the image content."


def sanitize_context_text(value: Any, max_len: int = 512) -> str:
    if not isinstance(value, str):
        return ""
    text = value.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    text = "".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in text)
    text = text.replace("<", "＜").replace(">", "＞")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def build_enhanced_caption_prompt(
    base_prompt: Any,
    *,
    user_prompt: Any = None,
    quoted_text: Any = None,
) -> str:
    user_str = sanitize_context_text(user_prompt)
    quote_str = sanitize_context_text(quoted_text)
    if not user_str and not quote_str:
        return str(base_prompt or QUOTE_IMAGE_CAPTION_BASE_PROMPT)

    base = str(base_prompt or QUOTE_IMAGE_CAPTION_BASE_PROMPT).strip()
    lines = [
        base,
        "",
        "<image_caption_context>",
        "下面是用户本轮请求的文字上下文。请结合这些文字理解用户想看图片里的什么，重点观察并描述图片中与用户提问相关的细节与事实；不要编造，也不要替主对话模型完成完整回复。",
    ]
    if user_str:
        lines.append(f"用户当前问题：{user_str}")
    if quote_str:
        lines.append(f"被引用消息文本：{quote_str}")
    lines.append("</image_caption_context>")
    return "\n".join(lines)


class ImageCaptionOptimizer:
    """包装 AstrBot 图像转述入口，使其结合用户当前提问看图。"""

    _original_ensure_img_caption: Any = None
    _installed: bool = False
    _active_instance: ImageCaptionOptimizer | None = None

    def __init__(self, logger: Any):
        self.logger = logger
        self.enabled = True

    def install(self) -> bool:
        if not self.enabled:
            return False
        cls = type(self)
        if cls._installed and cls._active_instance is self:
            return True

        astr_main_agent = self._load_astr_main_agent()
        if astr_main_agent is None or not hasattr(astr_main_agent, "_ensure_img_caption"):
            self._log("debug", "未找到 AstrBot _ensure_img_caption 入口，跳过图像转述优化包装")
            return False

        if cls._original_ensure_img_caption is None:
            cls._original_ensure_img_caption = astr_main_agent._ensure_img_caption
            original_ensure = cls._original_ensure_img_caption

            async def savage_ensure_img_caption(
                event: Any,
                req: Any,
                cfg: dict,
                plugin_context: Any,
                image_caption_provider: str,
            ) -> Any:
                active = cls._active_instance
                if active is None or not active.enabled:
                    return await original_ensure(event, req, cfg, plugin_context, image_caption_provider)

                optimized_cfg = dict(cfg) if isinstance(cfg, dict) else {}
                base_p = optimized_cfg.get("image_caption_prompt", QUOTE_IMAGE_CAPTION_BASE_PROMPT)
                user_p = getattr(req, "prompt", None) or getattr(event, "message_str", None)
                
                # 获取引用消息文本
                quote_text = ""
                message_obj = getattr(event, "message_obj", None)
                if message_obj and hasattr(message_obj, "message"):
                    for comp in message_obj.message:
                        if getattr(comp, "type", "") == "Reply" or comp.__class__.__name__ == "Reply":
                            quote_text = getattr(comp, "text", "") or ""
                            break

                enhanced_prompt = build_enhanced_caption_prompt(
                    base_p,
                    user_prompt=user_p,
                    quoted_text=quote_text,
                )
                optimized_cfg["image_caption_prompt"] = enhanced_prompt

                return await original_ensure(
                    event,
                    req,
                    optimized_cfg,
                    plugin_context,
                    image_caption_provider,
                )

            astr_main_agent._ensure_img_caption = savage_ensure_img_caption

        cls._active_instance = self
        cls._installed = True
        self._log("info", "SavageReply 已启用结合用户问题的智能图像转述增强")
        return True

    def terminate(self) -> None:
        cls = type(self)
        if cls._installed and cls._active_instance is self:
            if cls._original_ensure_img_caption:
                astr_main_agent = self._load_astr_main_agent()
                if astr_main_agent:
                    astr_main_agent._ensure_img_caption = cls._original_ensure_img_caption
            cls._original_ensure_img_caption = None
            cls._installed = False
            cls._active_instance = None

    def _load_astr_main_agent(self) -> Any | None:
        try:
            from astrbot.core import astr_main_agent
            return astr_main_agent
        except Exception:
            return None

    def _log(self, level: str, msg: str) -> None:
        func = getattr(self.logger, level, None)
        if callable(func):
            func(msg)


async def optimize_quoted_image_input(event: Any, req: Any, logger: Any | None = None) -> bool:
    """检查并补全当前请求遗漏的 Reply 引用图片。"""
    if event is None or req is None:
        return False

    message_obj = getattr(event, "message_obj", None)
    if not message_obj or not hasattr(message_obj, "message"):
        return False

    # 寻找 Reply 组件
    reply_comp = None
    for comp in message_obj.message:
        if getattr(comp, "type", "") == "Reply" or comp.__class__.__name__ == "Reply":
            reply_comp = comp
            break

    if not reply_comp:
        return False

    # 提取引用消息中的图片
    extracted_images: list[str] = []
    
    # 方式 1: 直接从 reply_comp 中的 images 属性获取
    imgs = getattr(reply_comp, "images", None) or getattr(reply_comp, "image_urls", None)
    if isinstance(imgs, list):
        for im in imgs:
            if isinstance(im, str) and im.strip():
                extracted_images.append(im.strip())

    # 方式 2: 使用 AstrBot 内置的 extract_quoted_message_images
    if not extracted_images:
        try:
            from astrbot.core.utils.quoted_message import extract_quoted_message_images
            refs = await extract_quoted_message_images(event, reply_comp)
            if isinstance(refs, list):
                for r in refs:
                    if isinstance(r, str) and r.strip():
                        extracted_images.append(r.strip())
        except Exception:
            pass

    if not extracted_images:
        return False

    # 检查 req.image_urls
    req_images = getattr(req, "image_urls", None)
    if req_images is None:
        try:
            req.image_urls = []
            req_images = req.image_urls
        except Exception:
            req_images = []

    # 查重并补充未包含的引用图片
    existing = set(req_images)
    new_added: list[str] = []
    for img in extracted_images:
        if img not in existing:
            req_images.append(img)
            existing.add(img)
            new_added.append(img)

    if not new_added:
        return False

    # 注入引用图片提示文本到 prompt
    notice = QUOTED_IMAGE_NOTICE.format(count=len(new_added))
    try:
        from astrbot.core.agent.message import TextPart
        part = TextPart(text=notice)
        if hasattr(part, "mark_as_temp"):
            part.mark_as_temp()
        extra = getattr(req, "extra_user_content_parts", None)
        if extra is not None and isinstance(extra, list):
            extra.append(part)
        else:
            cur_p = getattr(req, "prompt", "") or ""
            req.prompt = f"{notice}\n\n{cur_p}" if cur_p else notice
    except Exception:
        cur_p = getattr(req, "prompt", "") or ""
        req.prompt = f"{notice}\n\n{cur_p}" if cur_p else notice

    if logger:
        log_info = getattr(logger, "info", None)
        if callable(log_info):
            log_info(f"SavageReply 已成功为本轮请求补齐 {len(new_added)} 张引用消息图片")

    return True
