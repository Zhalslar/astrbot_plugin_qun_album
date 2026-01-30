from astrbot import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from .utils import (
    get_avatar,
    get_reply_text_async,
    get_replyer_id,
    get_member_rich_info,
)
from PIL import Image, ImageDraw, ImageFont
try:
    from pilmoji import Pilmoji
except ImportError:
    Pilmoji = None
import io
from pathlib import Path
import re

RESOURCES_DIR = Path(__file__).parent.parent / "resources"
FONT_PATH = RESOURCES_DIR / "fonts" / "NotoSansSC-Regular.ttf"
FONT_BOLD_PATH = RESOURCES_DIR / "fonts" / "NotoSansSC-Bold.ttf"

def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """加载字体"""
    target_font_path = FONT_BOLD_PATH if bold else FONT_PATH
    
    if target_font_path.exists():
        try:
            return ImageFont.truetype(str(target_font_path), size)
        except Exception:
            pass
            
    fallback_font_path = FONT_PATH if bold else FONT_BOLD_PATH
    if fallback_font_path.exists():
        try:
            return ImageFont.truetype(str(fallback_font_path), size)
        except Exception:
            pass

    return ImageFont.load_default()

def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """根据最大宽度对文本进行自动换行"""
    lines = []
    
    # 统一换行符并按行分割
    paragraphs = text.replace('\r\n', '\n').split('\n')
    
    for paragraph in paragraphs:
        # 如果是空行（比如连续换行），保留占位
        if not paragraph:
            lines.append("")
            continue
            
        current_line = ""
        for char in paragraph:
            test_line = current_line + char
            bbox = font.getbbox(test_line)
            # 兼容 getbbox 返回 None 的情况
            width = (bbox[2] - bbox[0]) if bbox else 0
            
            if width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = char
        if current_line:
            lines.append(current_line)
            
    return lines

def pad_emojis(text: str) -> str:
    try:
        import emoji
        pattern = emoji.get_emoji_regexp()
        return re.sub(pattern, lambda m: f" {m.group(0)} ", text)
    except Exception:
        return text

def draw_rounded_rectangle(draw: ImageDraw.ImageDraw, xy, corner_radius, fill=None, outline=None):
    """绘制圆角矩形"""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle((x1, y1, x2, y2), radius=corner_radius, fill=fill, outline=outline)

def make_italic(image: Image.Image, skew_factor: float = 0.1) -> Image.Image:
    """对图片应用错切变换以模拟斜体效果"""
    width, height = image.size
    new_width = width + int(height * abs(skew_factor))
    matrix = (1, skew_factor, 0, 0, 1, 0)
    
    return image.transform(
        (new_width, height),
        Image.AFFINE,
        matrix,
        resample=Image.BICUBIC
    )

def make_dialog_box(text: str, name_w: int) -> Image.Image:
    """创建对话气泡"""
    font_size = 55
    font = load_font(font_size, bold=False)
    max_text_width = 900
    
    lines = wrap_text(pad_emojis(text), font, max_text_width)
    
    text_width = 0
    text_height = 0
    line_spacing = 4 
    
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    
    for line in lines:
        bbox = font.getbbox(line)
        w = (bbox[2] - bbox[0]) if bbox else 0
        text_width = max(text_width, w)
        text_height += line_height + line_spacing
    
    if lines:
        text_height -= line_spacing
    
    box_w = max(text_width, name_w) + 130
    box_h = max(text_height + 103, 150)
    
    box = Image.new("RGBA", (int(box_w), int(box_h)), (0, 0, 0, 0))
    
    try:
        corner1 = Image.open(RESOURCES_DIR / "corner1.png").convert("RGBA")
        corner2 = Image.open(RESOURCES_DIR / "corner2.png").convert("RGBA")
        corner3 = Image.open(RESOURCES_DIR / "corner3.png").convert("RGBA")
        corner4 = Image.open(RESOURCES_DIR / "corner4.png").convert("RGBA")
    except FileNotFoundError:
        draw = ImageDraw.Draw(box)
        draw.rounded_rectangle((0, 0, box_w, box_h), radius=20, fill="white")
        return box
    
    box.paste(corner1, (0, 0))
    box.paste(corner2, (0, int(box_h - 75)))
    box.paste(corner3, (int(box_w - 70), 0))
    box.paste(corner4, (int(box_w - 70), int(box_h - 75)))
    
    fill_draw = ImageDraw.Draw(box)
    fill_draw.rectangle((65, 20, box_w - 65, box_h - 20), fill="white")
    fill_draw.rectangle((26, 75, box_w - 26, box_h - 75), fill="white")
    
    text_start_x = 65
    text_start_y = 17 + (box_h - 40 - text_height) // 2
    
    current_y = text_start_y
    if Pilmoji:
        logger.info("pilmoji")
        emoji_offset_y = max(1, int(descent * 0.9))
        with Pilmoji(box, emoji_position_offset=(0, emoji_offset_y)) as pilmoji:
            for line in lines:
                pilmoji.text((text_start_x, current_y), line, font=font, fill="black")
                current_y += line_height + line_spacing
    else:
        logger.info("no polo")
        for line in lines:
            fill_draw.text((text_start_x, current_y), line, font=font, fill="black")
            current_y += line_height + line_spacing
        
    return box

def render_my_friend(name: str, avatar_bytes: bytes, text: str, 
                    role: str = "member", title: str = "", level: int = 0, show_title: bool = True) -> bytes:
    """渲染包含头像、头衔、等级和对话框的完整表情包"""
    
    try:
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
    except Exception:
        avatar = Image.new("RGBA", (135, 135), "gray")
        
    mask = Image.new("L", (135, 135), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, 135, 135), fill=255)
    avatar = avatar.resize((135, 135))
    avatar.putalpha(mask)
    
    name_font = load_font(35, bold=False)
    name_bbox = name_font.getbbox(name)
    name_w = name_bbox[2] - name_bbox[0]
    name_h = name_bbox[3] - name_bbox[1]
    
    label_img = None
    label_w = 0
    label_h = 0
    
    if show_title:
        label_bg_color = "#9db2e0" 
        if role == "owner":
            label_bg_color = "#fdd93f"
        elif role == "admin":
            label_bg_color = "#3fe3d8"
            
        label_font = load_font(32, bold=False)
        lv_num_font = load_font(32, bold=True)
        lv_prefix_font = load_font(28, bold=True)
        
        lv_prefix = "LV"
        lv_num = str(level)
        
        p_bbox = lv_prefix_font.getbbox(lv_prefix)
        n_bbox = lv_num_font.getbbox(lv_num)
        
        p_w = p_bbox[2] - p_bbox[0]
        p_h = p_bbox[3] - p_bbox[1]
        n_w = n_bbox[2] - n_bbox[0]
        n_h = n_bbox[3] - n_bbox[1]
        
        lv_w = p_w + n_w + 4
        lv_h = max(p_h, n_h)
        
        buffer_w = 40
        buffer_h = 40
        lv_temp_img = Image.new("RGBA", (lv_w + buffer_w, lv_h + buffer_h), (0, 0, 0, 0))
        lv_temp_draw = ImageDraw.Draw(lv_temp_img)
        
        n_visual_top = (lv_h + buffer_h - n_h) // 2
        p_visual_top = n_visual_top + n_h - p_h
        
        lv_temp_draw.text((buffer_w // 2 - p_bbox[0], p_visual_top - p_bbox[1]), lv_prefix, font=lv_prefix_font, fill="white")
        lv_temp_draw.text((buffer_w // 2 + p_w + 4 - n_bbox[0], n_visual_top - n_bbox[1]), lv_num, font=lv_num_font, fill="white")
        
        lv_italic_img = make_italic(lv_temp_img, skew_factor=0.1)
        
        bbox = lv_italic_img.getbbox()
        if bbox:
            lv_italic_img = lv_italic_img.crop(bbox)
            
        final_title = title
        has_custom_title = bool(title)
        if not final_title:
            if role == "owner":
                final_title = "群主"
            elif role == "admin":
                final_title = "管理员"
            else:
                if 1 <= level <= 10:
                    final_title = "青铜"
                elif 11 <= level <= 20:
                    final_title = "白银"
                elif 21 <= level <= 40:
                    final_title = "黄金"
                elif 41 <= level <= 60:
                    final_title = "铂金"
                elif 61 <= level <= 80:
                    final_title = "钻石"
                elif level >= 81:
                    final_title = "王者"
        
        if role == "member" and has_custom_title:
            label_bg_color = "#d38ffe"
    
        title_img = None
        if final_title:
            title_text = final_title 
            title_bbox = label_font.getbbox(title_text)
            title_w = title_bbox[2] - title_bbox[0]
            title_h = title_bbox[3] - title_bbox[1]
            
            title_img = Image.new("RGBA", (title_w + 20, title_h + 20), (0, 0, 0, 0))
            if Pilmoji:
                t_ascent, t_descent = label_font.getmetrics()
                emoji_offset_y = max(1, int(t_descent * 0.6))
                with Pilmoji(title_img, emoji_position_offset=(0, emoji_offset_y)) as pilmoji:
                    pilmoji.text((-title_bbox[0] + 10, -title_bbox[1] + 10), title_text, font=label_font, fill="white")
            else:
                title_draw = ImageDraw.Draw(title_img)
                title_draw.text((-title_bbox[0] + 10, -title_bbox[1] + 10), title_text, font=label_font, fill="white")
            
            bbox = title_img.getbbox()
            if bbox:
                title_img = title_img.crop(bbox)
                
        content_w = lv_italic_img.width
        content_h = lv_italic_img.height
        
        spacing = int(label_font.getlength(" ") * 1.5)
        
        if title_img:
            content_w += spacing + title_img.width
            content_h = max(content_h, title_img.height)
            
        label_padding_x = 14
        label_padding_y = 10
        label_w = content_w + (label_padding_x * 2)
        label_h = content_h + (label_padding_y * 2)
        
        label_img = Image.new("RGBA", (int(label_w), int(label_h)), (0, 0, 0, 0))
        label_draw = ImageDraw.Draw(label_img)
        draw_rounded_rectangle(label_draw, (0, 0, label_w, label_h), 12, fill=label_bg_color)
        
        current_x = (label_w - content_w) / 2
        
        lv_y = (label_h - lv_italic_img.height) / 2
        label_img.paste(lv_italic_img, (int(current_x), int(lv_y)), mask=lv_italic_img)
        current_x += lv_italic_img.width
        
        if title_img:
            current_x += spacing 
            title_y = (label_h - title_img.height) / 2
            label_img.paste(title_img, (int(current_x), int(title_y)), mask=title_img)
    
    bubble_x = 165
    badge_x = 195
    
    box_img = make_dialog_box(text, 0)
    
    if show_title and label_img:
        name_x = badge_x + label_w + 10
    else:
        name_x = badge_x
        
    name_end_x = name_x + name_w
    bubble_end_x = bubble_x + box_img.width
    
    canvas_w = max(name_end_x, bubble_end_x) + 50
    canvas_h = box_img.height + 110
    canvas = Image.new("RGBA", (int(canvas_w), int(canvas_h)), "#eaedf4")
    
    canvas.paste(avatar, (20, 20), mask=avatar)
    canvas.paste(box_img, (bubble_x, 82), mask=box_img)
    if show_title and label_img:
        canvas.paste(label_img, (badge_x, 25), mask=label_img)
    
    name_draw_y = 20 + (35 - name_h) // 2
    
    if Pilmoji:
        n_ascent, n_descent = name_font.getmetrics()
        emoji_offset_y = max(1, int(n_descent * 0.6))
        with Pilmoji(canvas, emoji_position_offset=(0, emoji_offset_y)) as pilmoji:
            pilmoji.text((name_x, name_draw_y), name, font=name_font, fill="#868894")
    else:
        name_draw = ImageDraw.Draw(canvas)
        name_draw.text((name_x, name_draw_y), name, font=name_font, fill="#868894")
    
    output = io.BytesIO()
    canvas.convert("RGB").save(output, format="JPEG", quality=90)
    return output.getvalue()


async def generate_single_meme(bot, user_id: str, text: str, info: dict, show_title: bool = True) -> bytes | None:
    """获取头像并生成单张表情包"""
    avatar = await get_avatar(user_id)
    if not avatar:
        return None

    try:
        img_bytes = render_my_friend(
            name=info["nickname"],
            avatar_bytes=avatar,
            text=text,
            role=info["role"],
            title=info["title"],
            level=info["level"],
            show_title=show_title
        )
        return img_bytes
    except Exception as e:
        logger.exception(f"渲染失败: {e}")
        return None


async def generate_meme(event: AiocqhttpMessageEvent, show_title: bool = True) -> bytes | None:
    """处理消息事件并生成单张表情包"""
    reply_text = await get_reply_text_async(event)
    if not reply_text:
        return None

    replyer_id = get_replyer_id(event)
    if not replyer_id:
        return None

    group_id = int(event.get_group_id())
    user_id = int(replyer_id)
    
    info = await get_member_rich_info(event.bot, group_id, user_id)
    
    text = reply_text.strip()
    
    return await generate_single_meme(event.bot, replyer_id, text, info, show_title=show_title)


async def generate_stitched_meme(event: AiocqhttpMessageEvent, messages: list[dict], show_title: bool = True) -> bytes | None:
    """处理多条消息并生成垂直拼接的表情包"""
    images = []
    group_id = int(event.get_group_id())
    
    for msg in messages:
        user_id = msg["user_id"]
        text = msg["text"]
        
        info = await get_member_rich_info(event.bot, group_id, int(user_id))
        
        img_bytes = await generate_single_meme(event.bot, user_id, text, info, show_title=show_title)
        if img_bytes:
            images.append(Image.open(io.BytesIO(img_bytes)))
    
    if not images:
        return None
    
    try:
        width = max(img.width for img in images)
        total_height = sum(img.height for img in images)
        
        bg_color = "#eaedf4"
        with Image.new("RGB", (width, total_height), bg_color) as new_img:
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
