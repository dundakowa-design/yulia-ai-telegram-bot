import io
import os
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG_PATH = os.path.join(os.path.dirname(__file__), "assets", "stats_bg.png")


def build_stats_card(rem_caps, rem_rub, uniq_users, total_reqs, total_tokens, img_cnt, vis_cnt, txt_cnt):
    if not os.path.exists(BG_PATH):
        return None

    W, H = 1350, 900
    base = Image.open(BG_PATH).convert("RGBA")

    canvas = Image.new("RGBA", (W, H), (233, 240, 235, 255))
    scale = H / base.height
    nw, nh = int(base.width * scale), H
    base_resized = base.resize((nw, nh), Image.Resampling.LANCZOS)

    left_offset = -int(nw * 0.21)
    canvas.alpha_composite(base_resized, (left_offset, 0))

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    panel_left = 575
    panel_right = 1310
    draw.rounded_rectangle(
        (panel_left, 38, panel_right, 862),
        radius=36,
        fill=(247, 243, 234, 255),
        outline=(212, 178, 106, 255),
        width=4,
    )

    draw.line(((panel_left + 40, 130), (panel_right - 40, 130)), fill=(212, 178, 106, 210), width=3)

    # Нижняя мятная плашка с более компактной высотой (без лишней пустоты снизу)
    draw.rounded_rectangle(
        (panel_left + 32, 588, panel_right - 32, 830),
        radius=26,
        fill=(226, 241, 233, 255),
        outline=(168, 204, 186, 255),
        width=2,
    )

    # Увеличенные шрифты для комфортного чтения с телефона
    f_title = ImageFont.truetype(FONT_BOLD, 42)
    f_label = ImageFont.truetype(FONT_REG, 29)
    f_val_big = ImageFont.truetype(FONT_BOLD, 39)
    f_val = ImageFont.truetype(FONT_BOLD, 36)
    f_sub = ImageFont.truetype(FONT_BOLD, 29)
    f_task_lbl = ImageFont.truetype(FONT_REG, 25)
    f_task_val = ImageFont.truetype(FONT_BOLD, 36)

    c_dark = (36, 46, 42, 255)
    c_muted = (78, 90, 84, 255)
    c_gold_deep = (138, 98, 30, 255)
    c_mint_dark = (38, 104, 80, 255)

    draw.text((panel_left + 40, 64), "✦ Статистика Yulia AI", font=f_title, fill=c_dark)

    caps_str = f"~{rem_caps:,}".replace(",", " ") + f" CAPS (~{rem_rub} ₽)"
    tok_str = f"{total_tokens:,}".replace(",", " ")

    metrics = (
        ("Ориентировочный остаток:", caps_str, f_val_big, c_mint_dark),
        ("Активных пользователей:", str(uniq_users), f_val, c_dark),
        ("Всего запросов:", str(total_reqs), f_val, c_dark),
        ("Токенов учтено:", tok_str, f_val, c_dark),
    )

    # Больше воздуха между строками показателей
    y = 152
    for lbl, val, font_v, color_v in metrics:
        draw.text((panel_left + 40, y), lbl, font=f_label, fill=c_muted)
        draw.text((panel_left + 40, y + 38), val, font=font_v, fill=color_v)
        y += 106

    # Более контрастный заголовок мятного блока
    draw.text((panel_left + 54, 606), "По типам задач", font=f_sub, fill=c_gold_deep)

    col_w = (panel_right - panel_left - 64) // 3
    cols = (
        ("Генерация фото", str(img_cnt), panel_left + 32 + col_w // 2),
        ("Анализ фото", str(vis_cnt), panel_left + 32 + col_w + col_w // 2),
        ("Текст и поиск", str(txt_cnt), panel_left + 32 + col_w * 2 + col_w // 2),
    )
    for title_c, num_c, cx in cols:
        x0, y0, x1, y1 = draw.textbbox((0, 0), title_c, font=f_task_lbl)
        tw = x1 - x0
        draw.text((cx - tw // 2, 668), title_c, font=f_task_lbl, fill=c_muted)

        nx0, ny0, nx1, ny1 = draw.textbbox((0, 0), num_c, font=f_task_val)
        nw_txt = nx1 - nx0
        draw.text((cx - nw_txt // 2, 724), num_c, font=f_task_val, fill=c_dark)

    div1 = panel_left + 32 + col_w
    div2 = panel_left + 32 + col_w * 2
    draw.line(((div1, 662), (div1, 798)), fill=(168, 204, 186, 220), width=2)
    draw.line(((div2, 662), (div2, 798)), fill=(168, 204, 186, 220), width=2)

    result = Image.alpha_composite(canvas, overlay).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    buf.name = "yulia_stats.png"
    return buf
