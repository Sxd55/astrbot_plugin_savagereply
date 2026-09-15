"""Savage's Reply：发送前人味化——智能分段连发 + 打字延迟，完整性优先。"""

from __future__ import annotations

import asyncio

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.api.web import error_response, json_response, request

try:
    from .savagereply import PLUGIN_NAME, __version__
    from .savagereply.config import ReplyOptions
    from .savagereply.marker import build_marker_prompt, parse_marker
    from .savagereply.pacing import read_delay, segment_delay
    from .savagereply.policy import MODE_SPLIT, decide
    from .savagereply.segment import segments_from_marked, split_text
    from .savagereply.typing_status import (
        STOP_EVENT_TYPE,
        TYPING_EVENT_TYPE,
        set_input_status,
        should_show_typing,
    )
    from .savagereply.verify import scan_risks
except ImportError:
    from savagereply import PLUGIN_NAME, __version__
    from savagereply.config import ReplyOptions
    from savagereply.marker import build_marker_prompt, parse_marker
    from savagereply.pacing import read_delay, segment_delay
    from savagereply.policy import MODE_SPLIT, decide
    from savagereply.segment import segments_from_marked, split_text
    from savagereply.typing_status import (
        STOP_EVENT_TYPE,
        TYPING_EVENT_TYPE,
        set_input_status,
        should_show_typing,
    )
    from savagereply.verify import scan_risks

MIN_PRIORITY = -100000000000000000

BOOL_CONFIG_KEYS = (
    "enabled",
    "only_llm",
    "delay_enabled",
    "typing_enabled",
    "marker_enabled",
    "force_non_streaming",
    "protect_code_block",
    "protect_table",
    "protect_math",
    "verify_enabled",
    "verify_log_only",
)


def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _is_streaming(result) -> bool:
    name = getattr(getattr(result, "result_content_type", None), "name", "")
    return name in {"STREAMING_RESULT", "STREAMING_FINISH"}


def _is_model_result(result) -> bool:
    checker = getattr(result, "is_model_result", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:  # noqa: BLE001
            return False
    return False


@register(
    PLUGIN_NAME,
    "Sxd55",
    "Savage's Reply：LLM 长回复智能分段连发并模拟打字节奏，完整性优先。",
    __version__,
)
class SavageReplyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self._register_pages()
        logger.info("Savage's Reply loaded v%s", __version__)

    def _register_pages(self) -> None:
        apis = [
            ("config", self.page_config, ["GET"], "Plugin config snapshot"),
            ("config/save", self.page_config_save, ["POST"], "Save plugin toggles"),
        ]
        for route, handler, methods, desc in apis:
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/{route}",
                handler,
                methods,
                desc,
            )

    def _public_config(self) -> dict:
        options = ReplyOptions.from_config(self.config)
        return {
            "enabled": options.enabled,
            "only_llm": options.only_llm,
            "delay_enabled": options.delay_enabled,
            "typing_enabled": options.typing_enabled,
            "marker_enabled": options.marker_enabled,
            "force_non_streaming": options.force_non_streaming,
            "min_total_chars": options.min_total_chars,
            "max_total_chars": options.max_total_chars,
            "segment_min_chars": options.segment_min_chars,
            "segment_max_chars": options.segment_max_chars,
            "segment_hard_max_chars": options.segment_hard_max_chars,
            "max_segments": options.max_segments,
            "short_tail_chars": options.short_tail_chars,
            "paragraph_max_chars": options.paragraph_max_chars,
            "read_delay_min_seconds": options.read_delay_min_seconds,
            "read_delay_max_seconds": options.read_delay_max_seconds,
            "protect_code_block": options.protect_code_block,
            "protect_table": options.protect_table,
            "protect_math": options.protect_math,
            "verify_enabled": options.verify_enabled,
            "verify_log_only": options.verify_log_only,
            "platform_exclude": list(options.platform_exclude),
            "session_blacklist": list(options.session_blacklist),
        }

    async def page_config(self):
        return json_response({"values": self._public_config()})

    async def page_config_save(self):
        payload = await request.json(default={})
        values = payload.get("values") if isinstance(payload, dict) else None
        if not isinstance(values, dict):
            return error_response("bad payload", status_code=400)
        changed = {}
        for key, value in values.items():
            if key not in BOOL_CONFIG_KEYS:
                continue
            self.config[key] = _coerce_bool(value)
            changed[key] = self.config[key]
        if changed and hasattr(self.config, "save_config"):
            self.config.save_config()
        return json_response({"ok": True, "changed": changed, "values": self._public_config()})

    async def initialize(self):
        self._warn_builtin_segmented()

    def _builtin_segmented_enabled(self) -> bool:
        try:
            config = self.context.get_config()
            segmented = config.get("platform_settings", {}).get("segmented_reply", {})
            return bool(segmented.get("enable", False))
        except Exception:  # noqa: BLE001
            return False

    def _warn_builtin_segmented(self) -> None:
        try:
            enabled = self._builtin_segmented_enabled()
        except Exception as exc:  # noqa: BLE001
            logger.info("Savage's Reply: builtin segmented check failed: %s", exc)
            return
        if enabled:
            logger.warning(
                "Savage's Reply: AstrBot built-in segmented_reply is ON. "
                "The plugin will send every part itself to avoid double segmentation; "
                "disabling the built-in option in the AstrBot settings page is still recommended.",
            )
        else:
            logger.info(
                "Savage's Reply: builtin segmented_reply is off, plugin owns segmentation.",
            )

    @filter.event_message_type(filter.EventMessageType.ALL, priority=MIN_PRIORITY)
    async def on_message(self, event: AstrMessageEvent):
        """分段需要改写最终文本，流式结果改不动：本会话内先关掉框架流式。

        框架在 Agent 阶段读取 event extra `enable_streaming`，而消息处理在它之前，
        所以这里关掉才能拿回 on_decorating_result 的改写权（否则 [[next]] 会泄漏给用户）。
        """
        try:
            options = ReplyOptions.from_config(self.config)
            if not options.enabled or not options.force_non_streaming:
                return
            if event.get_platform_name() in set(options.platform_exclude):
                return
            if event.unified_msg_origin in set(options.session_blacklist):
                return
            event.set_extra("enable_streaming", False)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Savage's Reply streaming override skipped: %s", exc)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """每轮临时注入输出规范，让模型可以用 [[next]] 自己决定断句位置。"""
        try:
            options = ReplyOptions.from_config(self.config)
            if not options.enabled or not options.marker_enabled:
                return
            if event.get_platform_name() in set(options.platform_exclude):
                return
            if event.unified_msg_origin in set(options.session_blacklist):
                return
            prompt = options.marker_prompt.strip() or build_marker_prompt(
                options.max_segments,
            )
            self._append_temp_content(req, prompt)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Savage's Reply marker prompt skipped: %s", exc)

    @staticmethod
    def _append_temp_content(req: ProviderRequest, text: str) -> None:
        try:
            from astrbot.core.agent.message import TextPart

            part = TextPart(text=text)
            if hasattr(part, "mark_as_temp"):
                part.mark_as_temp()
            extra = getattr(req, "extra_user_content_parts", None)
            if extra is not None:
                extra.append(part)
                return
        except Exception:  # noqa: BLE001
            pass
        if getattr(req, "prompt", None):
            req.prompt = f"{text}\n\n{req.prompt}"
        else:
            req.prompt = text

    async def _tts_active(self, event: AstrMessageEvent) -> bool:
        """探测框架是否会在发送前用 TTS 把文本转成语音。

        若会，分段发送会把前半截发成文字、最后一段发成语音，必须整包交还框架。
        """
        try:
            config = self.context.get_config()
            settings = config.get("provider_tts_settings", {})
            if not settings.get("enable", False):
                return False
            try:
                from astrbot.core.star.session_llm_manager import SessionServiceManager

                if not await SessionServiceManager.should_process_tts_request(event):
                    return False
            except ImportError:
                return False
            provider = await self.context.get_using_tts_provider_async(
                event.unified_msg_origin,
            )
            return bool(provider)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Savage's Reply: tts probe skipped: %s", exc)
            return False

    @filter.on_decorating_result(priority=MIN_PRIORITY)
    async def on_decorating_result(self, event: AstrMessageEvent):
        try:
            await self._decorate(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Savage's Reply decorate failed: %s", exc)

    async def _decorate(self, event: AstrMessageEvent) -> None:
        result = event.get_result()
        if result is None or not result.chain:
            return
        if _is_streaming(result):
            return

        options = ReplyOptions.from_config(self.config)
        if not options.enabled:
            return
        if options.only_llm and not _is_model_result(result):
            return
        if event.get_platform_name() in set(options.platform_exclude):
            return
        if event.unified_msg_origin in set(options.session_blacklist):
            return
        if getattr(result, "_savagereply_processed", False):
            return
        setattr(result, "_savagereply_processed", True)

        chain = result.chain
        if any(not isinstance(comp, Plain) for comp in chain):
            return
        text = "".join(getattr(comp, "text", "") or "" for comp in chain)
        if not text.strip():
            return

        if options.verify_enabled:
            user_text = getattr(event, "message_str", "") or ""
            risks = scan_risks(text, options, user_text=user_text)
            if risks:
                logger.warning(
                    "Savage's Reply risk scan: %s",
                    "; ".join(f"{risk.kind}={risk.snippet!r}" for risk in risks),
                )
                if not options.verify_log_only and options.verify_suffix_text:
                    text = text.rstrip() + options.verify_suffix_text

        marked: list[str] | None = None
        # 始终解析：即使功能关闭，也要剥掉模型可能自己输出的标记，避免泄漏给用户。
        text, marked = parse_marker(text)
        if marked and not options.marker_enabled:
            marked = None

        if marked:
            segments = segments_from_marked(marked, options)
        else:
            decision = decide(text, options)
            if decision.mode != MODE_SPLIT:
                # text 已是剥掉标记后的干净文本：bypass 也要写回，否则标记泄漏给用户。
                result.chain = [Plain(text)]
                if options.debug_log:
                    logger.info("Savage's Reply bypass: %s", decision.reason)
                return
            segments = split_text(text, options)

        if len(segments) <= 1:
            result.chain = [Plain(text)]
            if options.debug_log:
                logger.info("Savage's Reply bypass: single_segment")
            return

        if options.debug_log:
            logger.info(
                "Savage's Reply split: %s segments, lengths=%s",
                len(segments),
                [len(seg) for seg in segments],
            )

        if await self._tts_active(event):
            if options.debug_log:
                logger.info(
                    "Savage's Reply: framework TTS active, hand back %s parts for per-part TTS.",
                    len(segments),
                )
            result.chain = [Plain(seg) for seg in segments]
            return

        await self._send_segments(
            event,
            result,
            segments,
            options,
            hand_back=not self._builtin_segmented_enabled(),
        )

    async def _send_segments(
        self,
        event: AstrMessageEvent,
        result,
        segments: list[str],
        options: ReplyOptions,
        hand_back: bool = True,
    ) -> None:
        """前 N-1 段自行发送；最后一段默认留在 result.chain 交给框架。

        hand_back=False（内置分段开启时）：最后一段也自行发送并清空 chain，
        避免框架把最后一段二次切碎。
        """
        sent = 0
        budget = options.delay_total_max_seconds
        typing_bot = None
        typing_user = ""
        if options.typing_enabled and options.delay_enabled:
            try:
                if should_show_typing(
                    event.get_platform_name(),
                    bool(event.get_group_id()),
                ):
                    typing_bot = getattr(event, "bot", None)
                    typing_user = str(event.get_sender_id() or "")
            except Exception:  # noqa: BLE001
                typing_bot = None
        framework_typing = (
            self._framework_typing_available(event)
            if (options.typing_enabled and options.delay_enabled and typing_bot is None)
            else False
        )

        first_delay = read_delay(options) if budget > 0 else 0.0
        first_delay = min(first_delay, budget)
        try:
            if first_delay > 0:
                # 真人不会秒回：先亮「正在输入」，再停顿一下再发第一条。
                if typing_bot:
                    await set_input_status(typing_bot, typing_user, TYPING_EVENT_TYPE)
                elif framework_typing:
                    await self._framework_typing(event, True)
                await asyncio.sleep(first_delay)
                budget = max(0.0, budget - first_delay)

            for index, segment in enumerate(segments):
                is_last = index == len(segments) - 1
                if is_last and hand_back:
                    result.chain = [Plain(segment)]
                    return
                await event.send(MessageChain().message(segment))
                sent += 1
                if is_last:
                    result.chain = []
                    return
                delay = segment_delay(segments[index + 1], options)
                delay = min(delay, budget)
                budget = max(0.0, budget - delay)
                if delay > 0:
                    if typing_bot:
                        await set_input_status(
                            typing_bot,
                            typing_user,
                            TYPING_EVENT_TYPE,
                        )
                    elif framework_typing:
                        await self._framework_typing(event, True)
                    await asyncio.sleep(delay)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Savage's Reply send failed at segment %s/%s, falling back: %s",
                sent + 1,
                len(segments),
                exc,
            )
            remaining = "".join(segments[sent:])
            result.chain = [Plain(remaining)] if remaining else []
        finally:
            if typing_bot:
                await set_input_status(typing_bot, typing_user, STOP_EVENT_TYPE)
            elif framework_typing:
                await self._framework_typing(event, False)

    @staticmethod
    def _framework_typing_available(event: AstrMessageEvent) -> bool:
        """平台是否实现了框架的 send_typing（webchat 的语义是 run_started，跳过）。"""
        try:
            from astrbot.core.platform.astr_message_event import AstrMessageEvent as BaseEvent

            if event.get_platform_name() == "webchat":
                return False
            return type(event).send_typing is not BaseEvent.send_typing
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    async def _framework_typing(event: AstrMessageEvent, active: bool) -> None:
        try:
            if active:
                await event.send_typing()
            else:
                await event.stop_typing()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Savage's Reply framework typing skipped: %s", exc)
