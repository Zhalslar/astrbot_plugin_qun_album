import asyncio
from datetime import datetime
import json
import os
import random
import re
import shutil
from pathlib import Path

from astrbot import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core import AstrBotConfig
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .src import draw as draw_module
from .src.font_manager import FontManager
from .src.utils import (
    check_group_level_permission,
    detect_image_ext,
    get_first_image,
    get_message_history,
    normalize_album_list_response,
    sanitize_filename,
    upload_album_image_with_fallback,
)

try:
    import emoji
    from emoji import unicode_codes

    if not hasattr(unicode_codes, "get_emoji_unicode_dict"):

        def get_emoji_unicode_dict(lang):
            return {
                data[lang]: char
                for char, data in emoji.EMOJI_DATA.items()
                if lang in data
            }

        unicode_codes.get_emoji_unicode_dict = get_emoji_unicode_dict

    if not hasattr(unicode_codes, "EMOJI_UNICODE"):
        unicode_codes.EMOJI_UNICODE = {"en": get_emoji_unicode_dict("en")}

    if not hasattr(emoji, "get_emoji_regexp"):
        _emoji_regexp = None

        def get_emoji_regexp():
            global _emoji_regexp
            if _emoji_regexp is None:
                emojis = sorted(emoji.EMOJI_DATA.keys(), key=len, reverse=True)
                pattern = "|".join(re.escape(e) for e in emojis)
                _emoji_regexp = re.compile(pattern)
            return _emoji_regexp

        emoji.get_emoji_regexp = get_emoji_regexp

except ImportError:
    pass


class AdminPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_qun_album")
        self._backend: str = "napcat"
        self._backend_client_id: int | None = None
        self.font_manager = FontManager(self.plugin_data_dir)
        self._font_task: asyncio.Task | None = None
        self._keywords: dict[str, dict[str, str]] = {}
        self._default_album_cache: dict[str, dict[str, str]] = {}

    async def initialize(self) -> None:
        self._font_task = asyncio.create_task(
            self._ensure_fonts(),
            name="qun-album-字体下载",
        )
        await self._init_keywords()

    async def _migrate_old_fonts(self) -> None:
        old_dir = Path(__file__).resolve().parent / "resources" / "fonts"
        if not old_dir.is_dir():
            return
        self.font_manager.font_dir.mkdir(parents=True, exist_ok=True)
        migrated = False
        for fname in (
            "NotoSansSC-Regular.ttf",
            "NotoSansSC-Bold.ttf",
            "NotoSansSC-Regular.otf",
            "NotoSansSC-Bold.otf",
        ):
            src = old_dir / fname
            if src.is_file():
                dst = self.font_manager.font_dir / fname
                if not dst.exists():
                    shutil.copy2(str(src), str(dst))
                    logger.info(f"[qun_album] 已迁移旧字体: {fname}")
                    migrated = True
        if migrated:
            draw_module.set_font_dir(self.font_manager.font_dir)

    def _build_backup_path(
        self, group_id: int, album_id: str, timestamp: str, ext: str
    ) -> Path:
        return (
            self.plugin_data_dir
            / "backup"
            / str(group_id)
            / str(album_id)
            / f"{timestamp}.{ext}"
        )

    def _albums_meta_path(self, group_id: int) -> Path:
        return self.plugin_data_dir / "backup" / str(group_id) / "_albums.json"

    def _read_albums_meta(self, group_id: int) -> dict:
        path = self._albums_meta_path(group_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _write_albums_meta(self, group_id: int, data: dict) -> None:
        path = self._albums_meta_path(group_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def _init_keywords(self) -> None:
        self._keywords.clear()
        groups = self.conf.get("random_album_groups", [])
        if not groups:
            return
        for gid in groups:
            meta = self._read_albums_meta(str(gid))
            kw_map: dict[str, str] = {}
            for aid, info in meta.items():
                if not isinstance(info, dict):
                    continue
                name = info.get("name", aid)
                keyword = sanitize_filename(name)
                if keyword:
                    kw_map[keyword] = str(aid)
            if kw_map:
                self._keywords[str(gid)] = kw_map

    async def _ensure_fonts(self) -> None:
        await self._migrate_old_fonts()
        ok = await self.font_manager.ensure_fonts()
        if ok:
            draw_module.set_font_dir(self.font_manager.font_dir)

    async def terminate(self) -> None:
        if self._font_task is not None and not self._font_task.done():
            self._font_task.cancel()
            try:
                await self._font_task
            except asyncio.CancelledError:
                pass

    async def _ensure_backend_detected(self, client) -> None:
        if client is None:
            return

        client_id = id(client)
        if self._backend_client_id == client_id:
            return

        self._backend_client_id = client_id
        self._backend = "napcat"

        try:
            version_info = await client.api.call_action("get_version_info")
            app_name = (
                version_info.get("app_name") if isinstance(version_info, dict) else None
            )
            if (
                app_name is None
                and isinstance(version_info, dict)
                and isinstance(version_info.get("data"), dict)
            ):
                app_name = version_info["data"].get("app_name")
            if app_name == "LLOneBot":
                self._backend = "llbot"
            elif app_name == "SnowLuma":
                self._backend = "snowluma"
            logger.debug(
                f"[qun_album] 懒探测协议端完成: "
                f"app_name={app_name or 'unknown'}, backend={self._backend}"
            )
        except Exception as e:
            logger.warning(f"[qun_album] 懒探测协议端失败，默认按 NapCat 处理: {e}")

    async def _get_album_by_name(
        self, event: AiocqhttpMessageEvent, name: str | None = None
    ) -> dict | None:
        await self._ensure_backend_detected(getattr(event, "bot", None))
        group_id = int(event.get_group_id())
        if self._backend in ("llbot", "snowluma"):
            raw_album_list = await event.bot.api.call_action(
                "get_group_album_list",
                group_id=group_id,
            )
        else:
            raw_album_list = await event.bot.get_qun_album_list(group_id=group_id)

        album_list = normalize_album_list_response(raw_album_list)
        if not album_list:
            return None
        if not name:
            return album_list[0]

        for album in album_list:
            album_name = album.get("name") or album.get("album_name")
            if album_name == name:
                return album
        return None

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("上传群相册", alias={"up"})
    async def upload_qun_album(self, event: AiocqhttpMessageEvent):
        """上传群相册"""
        await self._ensure_backend_detected(getattr(event, "bot", None))
        parts = event.message_str.strip().split()

        real_count = None
        real_album_name = None

        if len(parts) >= 3:
            if parts[-1].isdigit():
                real_count = int(parts[-1])
                real_album_name = " ".join(parts[1:-1])
            else:
                real_album_name = " ".join(parts[1:])
        elif len(parts) == 2:
            real_album_name = parts[1]

        group_id_str = str(event.get_group_id())

        # Default album fallback from config
        resolved_from_config = False
        if not real_album_name:
            default_albums = self.conf.get("default_albums", [])
            for entry in default_albums:
                if str(entry.get("group_id", "")) == group_id_str:
                    real_album_name = entry.get("album_name", "")
                    resolved_from_config = True
                    break

        # Resolve album ID (with caching for config-resolved names)
        used_cache = False
        if real_album_name:
            cached = self._default_album_cache.get(group_id_str, {})
            if cached.get("album_name") == real_album_name:
                album_id = cached["album_id"]
                resolved_album_name = real_album_name
                used_cache = True
            else:
                album = await self._get_album_by_name(event, real_album_name)
                if not album:
                    logger.warning(f"[qun_album] 上传目标相册不存在: {real_album_name}")
                    yield event.plain_result("该相册不存在")
                    return
                album_id = album.get("album_id")
                resolved_album_name = (
                    album.get("name") or album.get("album_name") or real_album_name
                )
                if resolved_from_config:
                    self._default_album_cache[group_id_str] = {
                        "album_name": real_album_name,
                        "album_id": album_id,
                    }
        else:
            album = await self._get_album_by_name(event, None)
            if not album:
                logger.warning(f"[qun_album] 上传目标相册不存在: {real_album_name}")
                yield event.plain_result("该相册不存在")
                return
            album_id = album.get("album_id")
            resolved_album_name = album.get("name") or album.get("album_name") or ""

        level_threshold = self.conf.get("level_threshold", 0)
        show_title = self.conf.get("show_title", True)

        is_allowed, current_level = await check_group_level_permission(
            event,
            level_threshold,
        )

        if not is_allowed:
            yield event.plain_result(
                f"你的群等级({current_level})不足，需要达到 {level_threshold} 级才能使用此指令"
            )
            return

        if real_count:
            messages = await get_message_history(event, real_count)
            if not messages:
                yield event.plain_result("获取历史消息失败，请确保是回复消息且消息存在")
                return
            image = await draw_module.generate_stitched_meme(
                event, messages, show_title=show_title
            )
        else:
            image = await get_first_image(event) or await draw_module.generate_meme(
                event, show_title=show_title
            )

        if not image:
            yield event.plain_result("需引用图片/文字")
            return

        group_id = int(event.get_group_id())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = detect_image_ext(image)
        use_backup = self.conf.get("backup_media", False)

        if use_backup:
            save_path = self._build_backup_path(group_id, str(album_id), timestamp, ext)
        else:
            save_path = self.plugin_data_dir / f"{group_id}_{timestamp}.{ext}"

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with save_path.open("wb") as f:
            f.write(image)

        # Upload with retry on cached album_id failure
        try:
            await upload_album_image_with_fallback(
                event=event,
                raw_group_id=group_id,
                raw_album_id=album_id,
                album_name=resolved_album_name,
                save_path=save_path,
                backend=self._backend,
            )
        except Exception:
            if used_cache:
                logger.info(
                    f"[qun_album] 缓存相册 ID 上传失败，尝试刷新: {group_id_str}/{real_album_name}"
                )
                self._default_album_cache.pop(group_id_str, None)
                album = await self._get_album_by_name(event, real_album_name)
                if album:
                    album_id = album.get("album_id")
                    resolved_album_name = (
                        album.get("name")
                        or album.get("album_name")
                        or real_album_name
                        or ""
                    )
                    await upload_album_image_with_fallback(
                        event=event,
                        raw_group_id=group_id,
                        raw_album_id=album_id,
                        album_name=resolved_album_name,
                        save_path=save_path,
                        backend=self._backend,
                    )
                else:
                    raise
            else:
                raise

        event.stop_event()
        logger.info(f"[qun_album] 上传图片到相册 {resolved_album_name} 成功")

        if not use_backup:
            os.remove(save_path)
            return

        meta = self._read_albums_meta(group_id)
        old = meta.get(str(album_id))
        if old and isinstance(old, dict) and old.get("name") != resolved_album_name:
            logger.info(
                f"[qun_album] 检测到相册改名: {old['name']} → {resolved_album_name}"
            )
        meta[str(album_id)] = {"name": resolved_album_name}
        self._write_albums_meta(group_id, meta)
        await self._init_keywords()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_random_album_keyword(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if not group_id:
            return
        gid_str = str(group_id)
        kw_map = self._keywords.get(gid_str)
        if not kw_map:
            return

        if not event.is_at_or_wake_command:
            return

        parts = event.message_str.strip().split()
        if not parts:
            return

        keyword = parts[0]
        if not keyword or keyword not in kw_map:
            return

        aid = kw_map[keyword]
        album_dir = self.plugin_data_dir / "backup" / gid_str / aid
        if not album_dir.is_dir():
            logger.warning(
                f"[qun_album] 关键词 '{keyword}' 匹配目录不存在: {album_dir}"
            )
            return

        files = [
            f
            for f in album_dir.iterdir()
            if f.is_file()
            and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp")
        ]
        if not files:
            return

        chosen = random.choice(files)
        logger.info(f"[qun_album] 关键词 '{keyword}' 触发 → 发送图片: {chosen.name}")
        yield event.image_result(str(chosen))
