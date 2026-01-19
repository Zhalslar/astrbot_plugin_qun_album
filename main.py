
from datetime import datetime
import os
from astrbot import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from .draw import generate_meme, generate_stitched_meme
from .utils import get_first_image, get_message_history, check_group_level_permission


@register(
    "astrbot_plugin_qun_album",
    "Zhalslar",
    "群相册插件，记录群友怪话",
    "1.0.4",
)
class AdminPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_qun_album")

    async def _get_album_id_by_name(
        self, event: AiocqhttpMessageEvent, name: str | None = None
    ) -> str | None:
        album_list = await event.bot.get_qun_album_list(
            group_id=int(event.get_group_id())
        )
        if not album_list:
            return None
        if not name:
            return album_list[0]["album_id"]
        for album in album_list:
            if album["name"] == name:
                return album["album_id"]

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("上传群相册", alias={"up"})
    async def upload_qun_album(self, event: AiocqhttpMessageEvent):
        """上传群相册"""
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
            
        album_id = await self._get_album_id_by_name(event, real_album_name)
        if not album_id:
            yield event.plain_result("该相册不存在")
            return

        # 检查群等级
        level_threshold = self.conf.get("level_threshold", 0)
        
        is_allowed, current_level = await check_group_level_permission(
            event,
            level_threshold
        )
        
        if not is_allowed:
            yield event.plain_result(f"你的群等级 ({current_level}) 不足，需要达到 {level_threshold} 级才能使用此指令")
            return

        if real_count:
            # 获取历史记录并生成拼接图
            messages = await get_message_history(event, real_count)
            if not messages:
                yield event.plain_result("获取历史消息失败，请确保是回复消息且消息存在")
                return
            image = await generate_stitched_meme(event, messages)
        else:
            image = await get_first_image(event) or await generate_meme(event)
            
        if not image:
            yield event.plain_result("需引用图片/文字")
            return

        group_id = int(event.get_group_id())
        save_path = (
            self.plugin_data_dir
            / f"{group_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        with save_path.open("wb") as f:
            f.write(image)

        await event.bot.upload_image_to_qun_album(
            group_id=group_id,
            album_id=album_id,
            album_name=real_album_name,
            file=str(save_path),
        )
        event.stop_event()
        logger.info("上传群相册成功")

        if not self.conf["save_image"]:
            os.remove(save_path)


