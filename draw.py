import asyncio
from astrbot import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from .utils import (
    get_avatar,
    get_reply_text_async,
    get_replyer_id,
    get_user_name,
)
from PIL import Image as PILImage
import io


async def generate_meme(event: AiocqhttpMessageEvent) -> bytes | None:
    """聊天记录转表情包（my_friend 模板）"""

    # 1. 收集素材，任何一步失败直接返回 None
    reply_text = await get_reply_text_async(event)
    if not reply_text:
        return None

    replyer_id = get_replyer_id(event)
    if not replyer_id:
        return None

    name = await get_user_name(
        client=event.bot,
        group_id=int(event.get_group_id()),
        user_id=int(replyer_id),
    )
    
    # 过滤掉回复文本中的首尾空白
    reply_text = reply_text.strip()
    
    return await generate_single_meme(event.bot, replyer_id, name, reply_text)

async def generate_single_meme(bot, user_id: str, name: str, text: str) -> bytes | None:
    """生成单个表情包"""
    avatar = await get_avatar(user_id)
    if not avatar:
        return None

    # 2. 动态导入 meme_generator，失败直接返回
    try:
        from meme_generator import get_memes
    except ImportError:
        logger.error("未安装 meme_generator")
        return None

    meme = next((m for m in get_memes() if m.key == "my_friend"), None)
    if not meme:
        logger.error("未找到 my_friend 模板")
        return None

    # 3. 根据版本号决定调用方式
    try:
        from meme_generator.version import __version__
    except ImportError:
        logger.error("无法读取 meme_generator 版本信息")
        return None

    if tuple(map(int, __version__.split("."))) <= (0, 2, 0):
        try:
            from meme_generator.utils import run_sync

            image_io = await run_sync(meme)(
                images=[avatar],
                texts=[text],
                args={"name": name},
            )
            return image_io.getvalue()
        except Exception as e:
            logger.exception(f"meme 生成失败: {e}")
            return None
    else:
        try:
            from meme_generator import Image as MemeImage

            image = await asyncio.to_thread(
                meme.generate,
                images=[MemeImage.open(io.BytesIO(avatar))],
                texts=[text],
                args={"name": name},
            )
            return image.getvalue() if hasattr(image, "getvalue") else image
        except Exception as e:
            logger.exception(f"meme 2 生成失败: {e}")
            return None

async def generate_stitched_meme(event: AiocqhttpMessageEvent, messages: list[dict]) -> bytes | None:
    """生成多张图片并拼接"""
    images = []
    for msg in messages:
        user_id = msg["user_id"]
        text = msg["text"]
        name = await get_user_name(
            client=event.bot,
            group_id=int(event.get_group_id()),
            user_id=int(user_id),
        )
        img_bytes = await generate_single_meme(event.bot, user_id, name, text)
        if img_bytes:
            images.append(PILImage.open(io.BytesIO(img_bytes)))
    
    if not images:
        return None
    
    try:
        # 拼接图片
        width = max(img.width for img in images)
        total_height = sum(img.height for img in images)
        
        # 使用第一张图片的左上角像素色作为底色，通常是 my_friend 模板的背景色
        bg_color = images[0].getpixel((0, 0))
        with PILImage.new("RGB", (width, total_height), bg_color) as new_img:
            y_offset = 0
            for img in images:
                new_img.paste(img, (0, y_offset))
                y_offset += img.height
            
            output = io.BytesIO()
            new_img.save(output, format="PNG")
            return output.getvalue()
    finally:
        for img in images:
            img.close()
