"""Savage's Reply：发送前人味化——智能分段连发 + 打字延迟，完整性优先。"""

from __future__ import annotations

import asyncio
import random

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import At, Image, Plain, Record, Reply
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.api.web import error_response, json_response, request

try:
    from .savagereply import PLUGIN_NAME, __version__
    from .savagereply.config import (
        ReplyOptions,
        _as_bool,
        _as_float,
        _as_int,
        _as_str_list,
    )
    from .savagereply.marker import build_marker_prompt, parse_marker
    from .savagereply.pacing import read_delay, segment_delay
    from .savagereply.policy import MODE_SPLIT, decide
    from .savagereply.segment import segments_from_marked, split_text, strip_emphasis
    from .savagereply.typing_status import (
        STOP_EVENT_TYPE,
        TYPING_EVENT_TYPE,
        set_input_status,
        should_show_typing,
    )
    from .savagereply.verify import scan_risks
    from .savagereply.gate import ActiveGate
except ImportError:
    from savagereply import PLUGIN_NAME, __version__
    from savagereply.config import (
        ReplyOptions,
        _as_bool,
        _as_float,
        _as_int,
        _as_str_list,
    )
    from savagereply.marker import build_marker_prompt, parse_marker
    from savagereply.pacing import read_delay, segment_delay
    from savagereply.policy import MODE_SPLIT, decide
    from savagereply.segment import segments_from_marked, split_text, strip_emphasis
    from savagereply.typing_status import (
        STOP_EVENT_TYPE,
        TYPING_EVENT_TYPE,
        set_input_status,
        should_show_typing,
    )
    from savagereply.verify import scan_risks
    from savagereply.gate import ActiveGate

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
    "strip_markdown_marks",
    "verify_enabled",
    "verify_log_only",
    "active_reply_enabled",
    "active_reply_unanswered_break",
)

INT_CONFIG_KEYS = (
    "min_total_chars",
    "max_total_chars",
    "segment_min_chars",
    "segment_max_chars",
    "segment_hard_max_chars",
    "max_segments",
    "short_tail_chars",
    "paragraph_max_chars",
    "active_reply_daily_limit",
)

FLOAT_CONFIG_KEYS = (
    "delay_base_seconds",
    "delay_per_char_seconds",
    "delay_punct_bonus_seconds",
    "delay_jitter",
    "delay_max_seconds",
    "delay_total_max_seconds",
    "read_delay_min_seconds",
    "read_delay_max_seconds",
    "active_reply_probability",
    "active_reply_cooldown",
    "active_reply_unanswered_seconds",
)

LIST_CONFIG_KEYS = (
    "platform_exclude",
    "session_blacklist",
    "active_reply_keywords",
    "active_reply_bot_names",
    "active_reply_groups",
)


def _coerce_bool(value, default: bool = False) -> bool:
    return _as_bool(value, default)


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
        self.gate = ActiveGate()
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
            "strip_markdown_marks": options.strip_markdown_marks,
            "verify_enabled": options.verify_enabled,
            "verify_log_only": options.verify_log_only,
            "platform_exclude": list(options.platform_exclude),
            "session_blacklist": list(options.session_blacklist),
            "active_reply_enabled": options.active_reply_enabled,
            "active_reply_mode": options.active_reply_mode,
            "active_reply_probability": options.active_reply_probability,
            "active_reply_keywords": list(options.active_reply_keywords),
            "active_reply_bot_names": list(options.active_reply_bot_names),
            "active_reply_cooldown": options.active_reply_cooldown,
            "active_reply_daily_limit": options.active_reply_daily_limit,
            "active_reply_unanswered_break": options.active_reply_unanswered_break,
            "active_reply_unanswered_seconds": options.active_reply_unanswered_seconds,
            "active_reply_quiet_hours": options.active_reply_quiet_hours,
            "active_reply_groups": list(options.active_reply_groups),
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
            self.config[key] = _as_bool(value, False)
            changed[key] = self.config[key]

        if changed:
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            elif hasattr(self.context, "save_config"):
                self.context.save_config()
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

    @staticmethod
    def _extract_target_ids(event: AstrMessageEvent) -> list[str]:
        targets: list[str] = []
        try:
            msg_obj = getattr(event, "message_obj", None)
            comps = getattr(msg_obj, "message", []) or []
            for comp in comps:
                if isinstance(comp, At):
                    target = getattr(comp, "qq", None) or getattr(comp, "target", None)
                    if target is not None:
                        targets.append(str(target))
                elif isinstance(comp, Reply):
                    sender = getattr(comp, "sender", None)
                    if sender:
                        sid = getattr(sender, "user_id", None) or getattr(sender, "id", None)
                        if sid is not None:
                            targets.append(str(sid))
        except Exception:  # noqa: BLE001
            pass
        return targets

    async def _reinject(self, event: AstrMessageEvent, text: str) -> None:
        """重新以唤醒状态将消息投递回 AstrBot 事件总线（打破冷场）。"""
        try:
            from astrbot.core.message.components import Plain
            from astrbot.core.star.star_tools import StarTools

            msg_obj = getattr(event, "message_obj", None)
            if not msg_obj:
                return
            message = await StarTools.create_message(
                type=str(getattr(msg_obj.type, "value", "group")),
                self_id=event.get_self_id(),
                session_id=event.session_id,
                sender=msg_obj.sender,
                message=[Plain(text)],
                message_str=text,
                group_id=event.get_group_id() or "",
                message_id=msg_obj.message_id,
            )
            await StarTools.create_event(
                abm=message,
                platform=event.get_platform_name(),
                is_wake=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Savage's Reply reinject failed: %s", exc)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """真人群聊活跃接话与冷场打破门禁。"""
        try:
            options = ReplyOptions.from_config(self.config)
            group_id = str(event.get_group_id() or "")
            sender_id = str(event.get_sender_id() or "")
            text = str(event.message_str or "").strip()
            bot_id = str(event.get_self_id() or "")
            target_ids = self._extract_target_ids(event)
            is_wake = getattr(event, "is_at_or_wake_command", False) or event.is_wake_up()

            # 内存环形队列实时记录群聊话轮上下文
            self.gate.record_turn(
                group_id=group_id,
                sender_id=sender_id,
                text=text,
                target_ids=target_ids,
                is_at_bot=is_wake,
            )

            if not options.active_reply_enabled:
                return
            if is_wake:
                return

            handled = bool(
                event.get_result()
                or event.get_extra("provider_request")
                or getattr(event, "_has_send_oper", False)
            )
            is_self = bool(bot_id and sender_id == bot_id)

            bot_names = list(options.active_reply_bot_names)
            if not bot_names:
                try:
                    cfg_name = self.context.get_config().get("bot_name")
                    if cfg_name:
                        bot_names.append(str(cfg_name))
                except Exception:  # noqa: BLE001
                    pass

            fire, reason = self.gate.evaluate(
                enabled=options.active_reply_enabled,
                is_group=bool(group_id),
                group_id=group_id,
                sender_id=sender_id,
                text=text,
                target_ids=target_ids,
                bot_id=bot_id,
                bot_names=bot_names,
                mode=options.active_reply_mode,
                probability=options.active_reply_probability,
                keywords=options.active_reply_keywords,
                groups_whitelist=options.active_reply_groups,
                quiet_hours=options.active_reply_quiet_hours,
                cooldown=options.active_reply_cooldown,
                daily_limit=options.active_reply_daily_limit,
                already_handled=handled,
                is_self=is_self,
            )

            if fire:
                event.is_at_or_wake_command = True
                event.set_extra("_savage_active_reply", True)
                self.gate.mark_fired(group_id)
                if options.debug_log:
                    logger.info(
                        "Savage's Reply active gate fired: reason=%s group=%s text=%s",
                        reason,
                        group_id,
                        text[:40],
                    )
                return

            # 冷场打破延时调度
            if options.active_reply_unanswered_break and self.gate.is_question_candidate(text):
                delay = options.active_reply_unanswered_seconds

                async def _do_unanswered_reply():
                    freq_ok, _ = self.gate.rate_limiter.check(
                        group_id=group_id,
                        cooldown=options.active_reply_cooldown,
                        daily_limit=options.active_reply_daily_limit,
                    )
                    if not freq_ok:
                        return
                    self.gate.mark_fired(group_id)
                    if options.debug_log:
                        logger.info("Savage's Reply cold break fired for: %s", text[:40])
                    await self._reinject(event, text)

                self.gate.schedule_unanswered(
                    group_id=group_id,
                    delay_seconds=delay,
                    asker_id=sender_id,
                    callback=_do_unanswered_reply,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Savage's Reply active gate error: %s", exc)

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

    def _tts_settings(self) -> dict:
        try:
            return dict(self.context.get_config().get("provider_tts_settings") or {})
        except Exception:  # noqa: BLE001
            return {}

    async def _tts_provider(self, event: AstrMessageEvent):
        """探测框架 TTS 是否会生效；返回 provider 或 None。

        注意：框架的 TTS 会把链里每个 Plain 各转成一条 Record，但整条链仍然
        只作为**一条消息**发出。所以分段必须在插件内自己做 TTS，不能把多段
        交还框架——否则用户只会收到一条合并的长语音。
        """
        try:
            settings = self._tts_settings()
            if not settings.get("enable", False):
                return None
            try:
                probability = float(settings.get("trigger_probability", 1.0))
            except (TypeError, ValueError):
                probability = 1.0
            if probability < 1.0 and random.random() > probability:
                return None
            try:
                from astrbot.core.star.session_llm_manager import SessionServiceManager

                if not await SessionServiceManager.should_process_tts_request(event):
                    return None
            except ImportError:
                return None
            provider = await self.context.get_using_tts_provider_async(
                event.unified_msg_origin,
            )
            return provider or None
        except Exception as exc:  # noqa: BLE001
            logger.debug("Savage's Reply: tts probe skipped: %s", exc)
            return None

    async def _tts_active(self, event: AstrMessageEvent) -> bool:
        """兼容旧调用：TTS 是否生效。"""
        return bool(await self._tts_provider(event))

    async def _tts_url(self, audio_path: str) -> str | None:
        """按框架配置决定音频要不要走文件服务（远程适配器需要 URL）。"""
        settings = self._tts_settings()
        if not settings.get("use_file_service"):
            return None
        try:
            callback_api_base = str(
                self.context.get_config().get("callback_api_base") or ""
            ).strip()
        except Exception:  # noqa: BLE001
            callback_api_base = ""
        if not callback_api_base:
            return None
        try:
            from astrbot.core import file_token_service

            token = await file_token_service.register_file(audio_path)
            return f"{callback_api_base}/api/file/{token}"
        except Exception as exc:  # noqa: BLE001
            logger.debug("Savage's Reply: tts file service skipped: %s", exc)
            return None

    async def _segment_chain(self, segment: str, tts_provider) -> MessageChain:
        """把一段文本变成要发送的消息链：TTS 开启时合成语音，失败回落文字。"""
        if tts_provider is None:
            return MessageChain().message(segment)
        try:
            audio_path = await tts_provider.get_audio(segment)
            if not audio_path:
                raise RuntimeError("TTS 未返回音频文件")
            url = await self._tts_url(audio_path)
            chain = MessageChain(
                chain=[Record(file=url or audio_path, url=url or audio_path, text=segment)],
            )
            if self._tts_settings().get("dual_output"):
                chain.message(segment)
            return chain
        except Exception as exc:  # noqa: BLE001
            logger.warning("Savage's Reply TTS failed, sending text instead: %s", exc)
            return MessageChain().message(segment)

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
        head_comps: list = []
        tail_comps: list = []
        plain_texts: list[str] = []
        seen_plain = False

        for comp in chain:
            if isinstance(comp, Plain):
                plain_texts.append(getattr(comp, "text", "") or "")
                seen_plain = True
            elif not seen_plain and isinstance(comp, (At, Reply)):
                head_comps.append(comp)
            else:
                tail_comps.append(comp)

        text = "".join(plain_texts)
        if not text.strip():
            return

        if options.strip_markdown_marks:
            # QQ 等不渲染 Markdown 的平台会把 ** 原样显示，发送前摘掉成对标记。
            text = strip_emphasis(text)

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
                result.chain = [*head_comps, Plain(text), *tail_comps]
                if options.debug_log:
                    logger.info("Savage's Reply bypass: %s", decision.reason)
                return
            segments = split_text(text, options)

        if len(segments) <= 1:
            result.chain = [*head_comps, Plain(text), *tail_comps]
            if options.debug_log:
                logger.info("Savage's Reply bypass: single_segment")
            return

        if options.debug_log:
            logger.info(
                "Savage's Reply split: %s segments, lengths=%s",
                len(segments),
                [len(seg) for seg in segments],
            )

        # 框架的 TTS 把每个 Plain 各转成一条 Record，但整条链只发一条消息；
        # 想「分段 + 语音」必须在插件里逐段合成、逐段发送。
        tts_provider = await self._tts_provider(event)
        if tts_provider and options.debug_log:
            logger.info(
                "Savage's Reply: TTS active, synthesizing %s segments one by one.",
                len(segments),
            )

        await self._send_segments(
            event,
            result,
            segments,
            options,
            tts_provider=tts_provider,
            head_comps=head_comps,
            tail_comps=tail_comps,
        )

    def _framework_headers(self, event: AstrMessageEvent) -> tuple[list, str]:
        """复刻框架 ResultDecorateStage 的回复头：引用 / @ / 回复前缀。

        框架在 on_decorating_result 之后才把这些加进 result.chain；插件全部自行发送后
        必须自己补上，且只补在第一段（与框架内置分段行为一致）。
        """
        try:
            settings = dict(self.context.get_config().get("platform_settings") or {})
        except Exception:  # noqa: BLE001
            settings = {}
        headers: list = []
        if settings.get("reply_with_quote"):
            message_id = ""
            try:
                message_id = str(getattr(event.message_obj, "message_id", "") or "")
            except Exception:  # noqa: BLE001
                message_id = ""
            if message_id:
                headers.append(Reply(id=message_id))
        if settings.get("reply_with_mention") and not event.is_private_chat():
            headers.append(At(qq=event.get_sender_id(), name=event.get_sender_name()))
        return headers, str(settings.get("reply_prefix") or "")

    async def _send_segments(
        self,
        event: AstrMessageEvent,
        result,
        segments: list[str],
        options: ReplyOptions,
        tts_provider=None,
        head_comps: list | None = None,
        tail_comps: list | None = None,
    ) -> None:
        """逐段自行发送并清空 result.chain。

        框架的回复头（引用 / @ / 回复前缀）在钩子之后才加到 result.chain 上；若把最后
        一段交还框架，会出现「前几段无引用、最后一段带引用」。这里全部自行发送，并把
        框架会加的回复头复刻到第一段（非纯文本段不加，与框架 can_decorate 一致）。
        tts_provider 非空时逐段合成语音发送（框架的 TTS 只会把整条链塞进一条消息）。
        同时保留原本的 head_comps（如现有 At/Reply）与 tail_comps（如 Image）。
        """
        sent = 0
        budget = options.delay_total_max_seconds
        head_comps = list(head_comps or [])
        tail_comps = list(tail_comps or [])
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

        headers, prefix = self._framework_headers(event)
        existing_types = {type(c) for c in head_comps}
        all_head = [h for h in headers if type(h) not in existing_types] + head_comps

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
                text = f"{prefix}{segment}" if index == 0 and prefix else segment
                chain = await self._segment_chain(text, tts_provider)
                if index == 0 and all_head and all(
                    isinstance(comp, (Plain, Image)) for comp in chain.chain
                ):
                    if isinstance(all_head[-1], At) and isinstance(chain.chain[0], Plain):
                        chain.chain[0].text = "\n" + chain.chain[0].text
                    chain.chain = [*all_head, *chain.chain]
                if index == len(segments) - 1 and tail_comps:
                    chain.chain = [*chain.chain, *tail_comps]
                await event.send(chain)
                sent += 1
                if index == len(segments) - 1:
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
            result.chain = [Plain(remaining), *tail_comps] if remaining else list(tail_comps)
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
