import io
import os
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(__file__)
BG_PATH = os.path.join(BASE_DIR, "assets", "stats_bg.png")
FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")

FALLBACK_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FALLBACK_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _load_font(weight_name, size, is_bold=False):
    path = os.path.join(FONTS_DIR, f"Manrope-{weight_name}.ttf")
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return ImageFont.truetype(path, size)
    return ImageFont.truetype(FALLBACK_BOLD if is_bold else FALLBACK_REG, size)


def build_stats_card(rem_caps, rem_rub, uniq_users, total_reqs, total_tokens, img_cnt, vis_cnt, txt_cnt):
    if not os.path.exists(BG_PATH):
        return None

    # Холст 1440x810 (пропорция 16:9, масштаб x2.25 от 640x360)
    W, H = 1440, 810
    base = Image.open(BG_PATH).convert("RGBA")
    canvas = base.resize((W, H), Image.Resampling.LANCZOS)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Границы родной золотой рамки на stats_bg.png (ничего поверх неё не заливаем)
    frame_left, frame_top = 45, 45
    frame_right, frame_bottom = 1068, 735
    pad_x = 54  # 24 px * 2.25 единый левый и правый внутренний отступ
    content_x = frame_left + pad_x

    # Палитра Premium Soft
    c_task_bg = (228, 238, 232, 195)     # #E4EEE8 лёгкий полупрозрачный фон блока задач
    c_divider = (216, 200, 167, 230)     # #D8C8A7 разделители
    c_text_main = (48, 59, 56, 255)      # #303B38 основной текст
    c_text_sub = (86, 98, 92, 255)       # #68736D (чуть плотнее для чёткости на стекле)
    c_balance = (40, 116, 95, 255)       # #28745F баланс
    c_accent = (186, 150, 91, 255)       # #BA965B акценты

    # Шрифты Manrope (масштаб x2.25)
    f_title = _load_font("Bold", 45, is_bold=True)        # 20 px
    f_balance = _load_font("Bold", 43, is_bold=True)      # 19 px
    f_val = _load_font("SemiBold", 36, is_bold=True)      # 16 px
    f_label = _load_font("Regular", 27, is_bold=False)    # 12 px
    f_sub_title = _load_font("Bold", 32, is_bold=True)    # 14 px
    f_cat_name = _load_font("Medium", 26, is_bold=False)  # 11.5 px
    f_cat_num = _load_font("Bold", 38, is_bold=True)      # 17 px

    # 1. Заголовок по левому краю внутри родной рамки
    draw.text((content_x, frame_top + 28), "Статистика Yulia AI", font=f_title, fill=c_text_main)

    # Горизонтальный разделитель #D8C8A7
    line_y = frame_top + 92
    draw.line(((content_x, line_y), (frame_right - pad_x, line_y)), fill=c_divider, width=2)

    # 2. Основные показатели с равномерными вертикальными интервалами
    caps_str = f"~{rem_caps:,}".replace(",", " ") + f" CAPS (~{rem_rub} ₽)"
    tok_str = f"{total_tokens:,}".replace(",", " ")

    metrics = (
        ("Ориентировочный остаток", caps_str, f_balance, c_balance),
        ("Активных пользователей", str(uniq_users), f_val, c_text_main),
        ("Всего запросов", str(total_reqs), f_val, c_text_main),
        ("Токенов учтено", tok_str, f_val, c_text_main),
    )

    y = line_y + 18
    step_y = 90
    for lbl, val, font_v, color_v in metrics:
        draw.text((content_x, y), lbl, font=f_label, fill=c_text_sub)
        draw.text((content_x, y + 32), val, font=font_v, fill=color_v)
        y += step_y

    # 3. Блок «По типам задач» (#E4EEE8) строго внутри золотой рамки
    box_left = content_x
    box_right = frame_right - pad_x
    box_top = frame_bottom - 182
    box_bottom = frame_bottom - 26

    draw.rounded_rectangle(
        (box_left, box_top, box_right, box_bottom),
        radius=22,
        fill=c_task_bg,
        outline=c_divider,
        width=2,
    )

    draw.text((box_left + 32, box_top + 15), "По типам задач", font=f_sub_title, fill=c_accent)

    inner_w = box_right - box_left
    col_w = inner_w // 3
    cols = (
        ("Генерация фото", str(img_cnt), box_left + col_w // 2),
        ("Анализ фото", str(vis_cnt), box_left + col_w + col_w // 2),
        ("Текст и поиск", str(txt_cnt), box_left + col_w * 2 + col_w // 2),
    )

    for title_c, num_c, cx in cols:
        x0, _, x1, _ = draw.textbbox((0, 0), title_c, font=f_cat_name)
        draw.text((cx - (x1 - x0) // 2, box_top + 62), title_c, font=f_cat_name, fill=c_text_sub)

        nx0, _, nx1, _ = draw.textbbox((0, 0), num_c, font=f_cat_num)
        draw.text((cx - (nx1 - nx0) // 2, box_top + 98), num_c, font=f_cat_num, fill=c_text_main)

    div1 = box_left + col_w
    div2 = box_left + col_w * 2
    draw.line(((div1, box_top + 60), (div1, box_bottom - 16)), fill=c_divider, width=2)
    draw.line(((div2, box_top + 60), (div2, box_bottom - 16)), fill=c_divider, width=2)

    result = Image.alpha_composite(canvas, overlay).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    buf.name = "yulia_stats.png"
    return buf
