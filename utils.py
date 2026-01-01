
import base64
from pathlib import Path
import random
from typing import Optional
from aiocqhttp import CQHttp
import aiohttp
from astrbot.api import logger
from astrbot.core.message.components import Image, Plain, Reply
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


async def download_image(url: str, http: bool = True) -> bytes | None:
    """下载图片"""
    if http:
        url = url.replace("https://", "http://")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.read()
    except Exception as e:
        logger.error(f"图片下载失败: {e}")
        return None

async def get_avatar(user_id: str) -> bytes | None:
    """根据 QQ 号下载头像"""
    # 简单容错：如果不是纯数字就随机一个
    if not user_id.isdigit():
        user_id = "".join(random.choices("0123456789", k=9))

    avatar_url = f"https://q4.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url, timeout=10) as resp:
                resp.raise_for_status()
                return await resp.read()
    except Exception as e:
        logger.error(f"下载头像失败: {e}")
        return None

async def load_bytes(src: str) -> bytes | None:
    """统一把 src 转成 bytes"""
    raw: Optional[bytes] = None
    # 1. 本地文件
    if Path(src).is_file():
        raw = Path(src).read_bytes()
    # 2. URL
    elif src.startswith("http"):
        raw = await download_image(src)
    # 3. Base64（直接返回）
    elif src.startswith("base64://"):
        return base64.b64decode(src[9:])
    return raw

async def get_first_image(event: AstrMessageEvent) -> bytes | None:
    """
    获取消息里的第一张图并以 Base64 字符串返回。
    顺序：
    1) 引用消息中的图片
    2) 当前消息中的图片
    找不到返回 None。
    """

    # ---------- 1. 先看引用 ----------
    reply_seg = next(
        (s for s in event.get_messages() if isinstance(s, Reply)), None
    )
    if reply_seg and reply_seg.chain:
        for seg in reply_seg.chain:
            if isinstance(seg, Image):
                if seg.url and (img := await load_bytes(seg.url)):
                    return img
                if seg.file and (img := await load_bytes(seg.file)):
                    return img

    # ---------- 2. 再看当前消息 ----------
    for seg in event.get_messages():
        if isinstance(seg, Image):
            if seg.url and (img := await load_bytes(seg.url)):
                return img
            if seg.file and (img := await load_bytes(seg.file)):
                return img


def get_replyer_id(event: AiocqhttpMessageEvent) -> str | None:
    """
    获取引用消息的文本
    """
    if reply_seg := next(
        (seg for seg in event.get_messages() if isinstance(seg, Reply)), None
    ):
        rid = reply_seg.sender_id
        return str(rid) if rid else None

def get_reply_text(event: AiocqhttpMessageEvent) -> str:
    """
    获取引用消息的文本
    """
    text = ""
    chain = event.get_messages()
    reply_seg = next((seg for seg in chain if isinstance(seg, Reply)), None)
    if reply_seg and reply_seg.chain:
        for seg in reply_seg.chain:
            if isinstance(seg, Plain):
                text = seg.text
    return text

async def get_user_name(client: CQHttp, user_id: int, group_id: int = 0) -> str:
    """
    获取群成员的昵称或群名片，无法获取则返回“未知用户”
    """
    if user_id == 0:
        return "未知"
    if group_id:
        member_info = await client.get_group_member_info(group_id=group_id, user_id=user_id)
        if name := member_info.get("card") or member_info.get("nickname"):
            return name
    name = (await client.get_stranger_info(user_id=user_id)).get("nickname")
    return name or "未知"

async def get_message_history(event: AiocqhttpMessageEvent, count: int) -> list[dict]:
    """
    获取回复的消息及其之上的 count-1 条消息。
    """
    # 获取被回复的消息 ID
    reply_seg = next((seg for seg in event.get_messages() if isinstance(seg, Reply)), None)
    if reply_seg:
        reply_msg_id = getattr(reply_seg, "id", None) or getattr(reply_seg, "message_id", None)
        logger.debug(f"[qun_album] 从 Reply 组件解析 reply_msg_id: {reply_msg_id}, Reply 对象: {reply_seg}")
    else:
        logger.debug(f"[qun_album] 未能解析到回复消息 ID. 消息链: {event.get_messages()}")
        return []

    reply_msg_id = str(reply_msg_id)
    group_id = int(event.get_group_id())
    logger.debug(f"[qun_album] 开始迭代搜索. 目标 ID: {reply_msg_id}, 群号: {group_id}, 计划获取数量: {count}")

    try:
        # 1. 先获取目标消息的时间戳，用于后续范围判定
        target_msg_res = await event.bot.get_msg(message_id=reply_msg_id)
        target_time = target_msg_res.get("time") if isinstance(target_msg_res, dict) else None
        
        if not target_time:
            logger.error(f"[qun_album] 无法获取目标消息 {reply_msg_id} 的时间戳")
            return []
            
        logger.debug(f"[qun_album] 目标消息时间戳: {target_time}")

        # 2. 采用迭代搜索的方式，从最新消息开始逐步扩大范围
        # 起始 100 条，其次 1000，然后 2000 依次翻倍，上限 32000
        search_counts = [100, 1000, 2000, 4000, 8000, 16000, 32000]
        target_messages = []
        
        for search_count in search_counts:
            # 获取最新的 search_count 条消息，使用正序获取，即 [旧, ..., 最新]
            res = await event.bot.get_group_msg_history(
                group_id=group_id, 
                message_seq=0, 
                count=search_count,
                reverseOrder=False
            )
            
            messages = res.get("messages", []) if isinstance(res, dict) else res
            if not messages:
                continue
            
            # 获取当前批次最老的消息时间
            earliest_time = messages[0].get("time")
            logger.debug(f"[qun_album] 搜索范围 {search_count}: 最早时间 {earliest_time}, 目标时间 {target_time}")

            # 如果当前批次的最早时间已经早于或等于目标时间，说明目标消息必然在当前批次内
            if earliest_time <= target_time:
                # 查找目标消息在当前列表中的位置
                target_idx = -1
                for i, msg in enumerate(messages):
                    if str(msg.get("message_id")) == reply_msg_id:
                        target_idx = i
                        break
                
                if target_idx != -1:
                    logger.debug(f"[qun_album] 找到目标. target_idx: {target_idx}, 计划获取有效消息数量: {count}")
                    
                    target_messages = []
                    # 从 target_idx 开始往前找（往旧的方向找），直到找齐 count 条有效消息
                    for i in range(target_idx, -1, -1):
                        msg = messages[i]
                        sender_id = str(msg.get("user_id") or msg.get("sender", {}).get("user_id"))
                        text = ""
                        raw_msg = msg.get("message")
                        
                        if isinstance(raw_msg, list):
                            for seg in raw_msg:
                                if seg.get("type") == "text":
                                    text += seg.get("data", {}).get("text", "")
                        elif isinstance(raw_msg, str):
                            text = raw_msg

                        if text.strip():
                            target_messages.append({
                                "user_id": sender_id,
                                "text": text,
                                "message_id": msg.get("message_id")
                            })
                        
                        if len(target_messages) >= count:
                            break
                    
                    target_messages.reverse()
                    
                    logger.debug(f"[qun_album] 最终获取到的有效消息列表(正序): {[m['text'] for m in target_messages]}")
                    return target_messages
                else:
                    logger.warning(f"[qun_album] 时间戳判定在范围内但未找到 ID: {reply_msg_id}，继续扩大搜索范围")
                        
        logger.error(f"在最近 32000 条消息中未找到目标消息 ID: {reply_msg_id}")
        return []
        
    except Exception as e:
        logger.error(f"获取历史记录失败: {e}")
        return []
