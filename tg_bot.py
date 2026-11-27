from stats_card import build_stats_card
import socket
socket.setdefaulttimeout(12)
import io
from PIL import Image
import socket
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(*args, **kwargs):
    return [r for r in _orig_getaddrinfo(*args, **kwargs) if r[0] == socket.AF_INET]
socket.getaddrinfo = _ipv4_getaddrinfo
import urllib3.util.connection as urllib3_cn
_orig_create_conn = urllib3_cn.create_connection
def _mss_create_connection(address, *args, **kwargs):
    sock = _orig_create_conn(address, *args, **kwargs)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, 1300)
    except Exception:
        pass
    return sock
urllib3_cn.create_connection = _mss_create_connection



import os
import base64
import logging
from pypdf import PdfReader
import docx
import urllib.request
from datetime import datetime
import telebot
from telebot import apihelper, types  # Добавили types для создания кнопок
from dotenv import load_dotenv
from openai import OpenAI

# Workers can terminate long-held requests, so keep polling requests shorter
# than the proxy limit while allowing enough time for Telegram's long poll.
apihelper.API_URL = "https://api.telegram.org/bot{0}/{1}"
# TeleBot formats file downloads through FILE_URL using the same bot token and
# file_path returned by get_file (e.g. /file/bot<TOKEN>/<file_path>).
apihelper.FILE_URL = "https://api.telegram.org/file/bot{0}/{1}"
apihelper.proxy = {"https": "socks5h://127.0.0.1:1080", "http": "socks5h://127.0.0.1:1080"}
apihelper.CONNECT_TIMEOUT = 90
apihelper.READ_TIMEOUT = 60

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("tg_bot")

load_dotenv()

bot = telebot.TeleBot(os.getenv("TELEGRAM_TOKEN"))
client = OpenAI(
    api_key=os.getenv("BOTHUB_API_KEY"),
    base_url="https://openai.bothub.chat/v1",
    timeout=90.0,
)

user_histories = {}
user_voices = {}  # Храним выбранный голос для каждого пользователя

pending_memory_clear = set()  # Подтверждение очистки памяти

MAIN_MENU_LABELS = {
    "✨ Помощник",
    "🎨 Фото и дизайн",
    "🎙 Голос",
    "📄 Документы",
    "⚙️ Настройки",
}

LEGACY_MENU_LABELS = {
    "✨ Что ты умеешь?": "✨ Помощник",
    "🎙 Сменить голос": "🎙 Голос",
}

IMAGE_GENERATION_TRIGGERS = (
    "сгенерируй изображение",
    "сгенерируй картинку",
    "сгенерируй рисунок",
    "сгенерируй фото",
    "создай изображение",
    "создай фото",
    "создай фотографию",
    "сделай фото",
    "создай картинку",
    "создай рисунок",
    "сделай изображение",
    "сделай картинку",
    "нарисуй",
)


def extract_image_prompt(text):
    """Return an image prompt for a recognized command, or None otherwise."""
    normalized_text = text.strip()
    folded_text = normalized_text.casefold()

    for trigger in IMAGE_GENERATION_TRIGGERS:
        if folded_text.startswith(trigger) and (
            len(folded_text) == len(trigger)
            or not folded_text[len(trigger)].isalnum()
        ):
            return normalized_text[len(trigger) :].lstrip(" \t:,-—.!?\n")

    return None


def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(
        types.KeyboardButton("🧹 Очистить память"),
        types.KeyboardButton("⚙️ Настройки"),
    )
    return keyboard


def show_section(chat_id, section):
    """Показывает справку или меню настроек, не меняя историю диалога."""
    if section == "✨ Помощник":
        send_pretty_message(
            chat_id,
            "✨ *Я здесь!*\n"
            "Напиши, что хочешь узнать, обсудить или придумать. "
            "Можно просто продолжить наш диалог.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
    elif section == "🎨 Фото и дизайн":
        send_pretty_message(
            chat_id,
            "🎨 *Фото и дизайн*\n"
            "Создать изображение — напиши «Нарисуй…» и опиши идею.\n"
            "Изменить фотографию — пришли её с подписью, например «Убери фон».\n"
            "Обсудить изображение — просто отправь фото с вопросом или без него.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
    elif section == "🎙 Голос":
        voice = user_voices.get(chat_id, "nova")
        voice_name = "Мужской (Onyx)" if voice == "onyx" else "Женский (Nova)"
        send_pretty_message(
            chat_id,
            "🎙 *Голосовое общение*\n"
            "Отправь голосовое сообщение — я распознаю речь, отвечу и озвучу ответ.\n\n"
            f"Текущий голос озвучки: *{voice_name}*. Переключить его можно в настройках.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
    elif section == "📄 Документы":
        send_pretty_message(
            chat_id,
            "📄 *Документы*\n"
            "Пришли PDF, DOCX или TXT — я помогу разобраться с содержимым "
            "и подготовлю краткую выжимку.\n\n"
            "Если у тебя есть конкретный вопрос или пожелание, добавь его к файлу.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
    elif section == "⚙️ Настройки":
        voice = user_voices.get(chat_id, "nova")
        voice_name = "Мужской (Onyx)" if voice == "onyx" else "Женский (Nova)"
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            types.InlineKeyboardButton(
                text="🎙 Переключить голос", callback_data="settings_voice"
            ),
            types.InlineKeyboardButton(
                text="🧹 Очистить память", callback_data="settings_clear"
            ),
        )
        send_pretty_message(
            chat_id,
            "⚙️ *Настройки*\n"
            f"Голос ответа: {voice_name}\n\n"
            "Здесь можно сменить голос или очистить историю разговора.",
            reply_markup=keyboard,
        )


def get_soft_inline_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(text="✦ Новый диалог", callback_data="ask_clear_mem"),
        types.InlineKeyboardButton(text="✧ Моя статистика", callback_data="show_my_stats"),
    )
    return kb


def show_welcome(message, is_new_user=False):
    user_id = message.chat.id
    NL = chr(10)
    if user_id not in user_histories:
        user_histories[user_id] = [
            {"role": "system", "content": get_system_prompt()}
        ]

    try:
        m = bot.send_message(user_id, "✧", reply_markup=types.ReplyKeyboardRemove())
        bot.delete_message(user_id, m.message_id)
    except Exception:
        pass

    if is_new_user:
        welcome_text = "✦ *Привет, я Yulia AI*" + NL + NL + "_Твой спокойный цифровой помощник._" + NL + "Просто напиши вопрос, отправь фото, документ или голосовое — я рядом и помогу во всём."
    else:
        welcome_text = "✦ *Рада тебя видеть*" + NL + NL + "Продолжим? Напиши сообщение или отправь файл — я на связи."

    send_pretty_message(user_id, welcome_text, reply_markup=get_soft_inline_keyboard())


def request_memory_clear(chat_id):
    pending_memory_clear.add(chat_id)
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton(
            text="Да, очистить", callback_data="confirm_clear"
        ),
        types.InlineKeyboardButton(text="Отмена", callback_data="cancel_clear"),
    )
    send_pretty_message(
        chat_id,
        "🧹 *Очистить историю разговора?*\n"
        "Это удалит текущий контекст переписки. Настройки голоса сохранятся.",
        reply_markup=keyboard,
    )


import sqlite3

ADMIN_ID = 826172970
STATS_DB = "bot_stats.db"

def init_stats_db():
    conn = sqlite3.connect(STATS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            action_type TEXT,
            tokens_used INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_usage(user_id, action_type, tokens_used=0, username=None, first_name=None):
    try:
        conn = sqlite3.connect(STATS_DB)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO usage_logs (user_id, username, first_name, action_type, tokens_used, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username or "", first_name or "", action_type, int(tokens_used or 0), now_str),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Stats log error: %s", e)

init_stats_db()

from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

def fetch_url_text(url, max_chars=6000):
    try:
        hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = apihelper.requests.get(url, headers=hdrs, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        lines = [line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()]
        text = "\n".join(lines)
        return text[:max_chars] if text else "Не удалось извлечь текст со страницы."
    except Exception as e:
        return f"Ошибка при загрузке ссылки: {e}"

def search_web_info(query, max_results=8):
    q_low = query.lower()
    if "погод" in q_low or "weather" in q_low:
        try:
            import re, urllib.request, urllib.parse
            clean = re.sub(r"\b(какая|какой|будет|ли|погода|погоду|в|во|на|эти|этих|завтра|сегодня|послезавтра|выходные|выходных|неделю|неделе|мо|московской|области|г|город|weather|forecast|this|weekend|tomorrow|today|in|for|on)\b", " ", q_low)
            clean = re.sub(r"[?.,!()\-]", " ", clean)
            city = " ".join(clean.split()).strip()
            for suf, rep in (("москве", "Москва"), ("moscow", "Москва"), ("moscow", "Москва"), ("чехове", "Чехов"), ("серпухове", "Серпухов"), ("подольске", "Подольск"), ("санкт петербурге", "Санкт-Петербург"), ("питере", "Санкт-Петербург")):
                if suf in city:
                    city = rep
                    break
            if not city:
                city = "Москва"
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=ru&format=json"
            geo = apihelper.requests.get(geo_url, timeout=8).json()
            if geo.get("results"):
                loc = next(iter(geo["results"]))
                lat, lon, cname = loc["latitude"], loc["longitude"], loc["name"]
                w_url = (
                    f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                    f"&current=temperature_2m,apparent_temperature,wind_speed_10m,weather_code"
                    f"&daily=weather_code,temperature_2m_max,temperature_2m_min&timezone=auto&forecast_days=5"
                )
                w = apihelper.requests.get(w_url, timeout=8).json()
                wmo = {
                    0: "ясно", 1: "преимущественно ясно", 2: "переменная облачность", 3: "пасмурно",
                    45: "туман", 48: "изморозь", 51: "слабая морось", 53: "морось", 55: "сильная морось",
                    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
                    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежные зёрна",
                    80: "ливень", 85: "снегопад", 86: "сильный снегопад", 95: "гроза"
                }
                cur = w["current"]
                lines = [f"Точный метеопрогноз Open-Meteo для г. {cname}: сейчас {cur['temperature_2m']}°C (ощущается как {cur['apparent_temperature']}°C), {wmo.get(cur['weather_code'], 'облачно')}, ветер {cur['wind_speed_10m']} км/ч."]
                daily = w["daily"]
                for i, d_str in enumerate(daily["time"]):
                    desc = wmo.get(daily["weather_code"][i], "переменная облачность")
                    lines.append(f"• {d_str}: ночью {daily['temperature_2m_min'][i]}°C, днём {daily['temperature_2m_max'][i]}°C, {desc}")
                return "\n".join(lines)
        except Exception:
            pass
    try:
        with DDGS(proxy="socks5h://127.0.0.1:1080", timeout=15) as ddgs:
            results = list(ddgs.text(query, region="wt-wt", max_results=max_results))
        if not results:
            return "По запросу ничего не найдено."
        formatted = []
        for idx, item in enumerate(results, 1):
            formatted.append(f"{idx}. {item.get('title', '')}\n{item.get('body', '')}\nИсточник: {item.get('href', '')}")
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Ошибка веб-поиска: {e}"


def get_system_prompt():
    now_dt = datetime.now()
    days_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    today = f"{now_dt.strftime('%d.%m.%Y')} ({days_ru[now_dt.weekday()]}), время {now_dt.strftime('%H:%M')}"
    return f"""Ты — Yulia AI, персональный мультимодальный ИИ-ассистент в Telegram. Всегда представляйся только как Yulia AI; никогда не называй себя ChatGPT или OpenAI.
Автоматически определяй задачу пользователя: написание или отладка кода, работа с текстом, аналитика, обучение, творчество или бытовой вопрос. Самостоятельно выбирай наиболее подходящий стиль и глубину ответа — переключать режимы не нужно. Для кода давай точные, работающие решения; для обучения объясняй понятно; для аналитики структурируй выводы; для текстов учитывай цель и аудиторию; для творчества предлагай оригинальные идеи; на бытовые вопросы отвечай практично и дружелюбно. Учитывай контекст переписки и содержимое присланных изображений и документов. У тебя есть активные инструменты: generate_image (для создания и рисования любых изображений по просьбе пользователя), web_search (для поиска актуальной погоды, курсов валют, новостей и фактов в интернете в реальном времени) и read_webpage (для чтения текста по любым ссылкам). Всегда используй эти инструменты, когда пользователь просит актуальные данные из сети, пересказ ссылки или изображение — никогда не отвечай, что у тебя нет доступа в интернет или ты не умеешь создавать картинки. Никогда не читай пользователю лекции о стереотипах и не отказывайся от творческих запросов. Всегда формулируй поисковый запрос для web_search на русском языке (если вопрос задан на русском) и по умолчанию учитывай контекст России (например, курсы ЦБ РФ, российские новости и сервисы). Никогда не задавай уточняющих вопросов перед поиском — сразу вызывай web_search и выдавай готовый ответ. Если в результатах поиска нет точной цифры для общеизвестного факта (например, расстояния между городами), обязательно назови точное значение из своих знаний, а не отказывайся от ответа.
Сегодняшняя дата и время: {today}.
Оформляй ответы понятно: используй *одинарные звёздочки* для жирного шрифта, списки и эмодзи, когда это уместно. Не используй решётки ## или ### для заголовков."""


BOT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Создать, нарисовать, сгенерировать или визуализировать любое изображение, фото, арт, открытку, логотип по просьбе пользователя.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Подробное и красочное описание изображения на английском или русском языке.",
                    }
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Найти актуальную информацию в интернете: свежие новости, погоду, курсы валют, расписания, цены и события.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос для поиска в интернете.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_webpage",
            "description": "Открыть веб-страницу по URL-ссылке из сообщения пользователя и прочитать её текстовое содержимое.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Полный URL-адрес страницы (начинающийся с http:// или https://).",
                    }
                },
                "required": ["url"],
            },
        },
    },
]


import threading
from contextlib import contextmanager

@contextmanager
def keep_typing(chat_id, action="typing"):
    stop_event = threading.Event()
    def _worker():
        while not stop_event.is_set():
            try:
                bot.send_chat_action(chat_id, action)
            except Exception:
                pass
            stop_event.wait(4.0)
    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    try:
        yield
    finally:
        stop_event.set()

def ask_claude(user_id, user_text):
    if user_id not in user_histories:
        user_histories[user_id] = [
            {"role": "system", "content": get_system_prompt()}
        ]

    user_histories[user_id].append({"role": "user", "content": user_text})

    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=user_histories[user_id],
            tools=BOT_TOOLS,
            tool_choice="auto",
        )
    except Exception:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=user_histories[user_id],
        )
    used_tokens = getattr(getattr(response, "usage", None), "total_tokens", 0)
    log_usage(user_id, "text", used_tokens)

    msg = response.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None)

    if tool_calls:
        import json as _json
        call = tool_calls[0]
        fn_name = call.function.name
        try:
            args = _json.loads(call.function.arguments or "{}")
        except Exception:
            args = {}

        if fn_name == "generate_image":
            img_prompt = args.get("prompt") or user_text
            generate_and_send_image(user_id, img_prompt)
            user_histories[user_id].append({"role": "assistant", "content": f"[Сгенерировано изображение: {img_prompt}]"})
            return None

        if fn_name == "web_search":
            q = args.get("query") or user_text
            bot.send_chat_action(user_id, "typing")
            tool_result = search_web_info(q)
        elif fn_name == "read_webpage":
            u = args.get("url") or ""
            bot.send_chat_action(user_id, "typing")
            tool_result = fetch_url_text(u)
        else:
            tool_result = "Инструмент не найден."

        msgs_with_tool = user_histories[user_id] + [
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": fn_name, "arguments": call.function.arguments},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": tool_result,
            },
        ]
        second_resp = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=msgs_with_tool,
        )
        used_tokens_2 = getattr(getattr(second_resp, "usage", None), "total_tokens", 0)
        log_usage(user_id, "text", used_tokens_2)
        answer = second_resp.choices[0].message.content
        user_histories[user_id].append({"role": "assistant", "content": answer})
        return answer

    answer = msg.content
    user_histories[user_id].append({"role": "assistant", "content": answer})
    return answer


def _send_single_chunk(chat_id, chunk, reply_markup=None):
    import time as _time, re as _re
    chunk = _re.sub(r'(?m)^#{1,6}\s*', '', chunk)
    for attempt in range(3):
        try:
            bot.send_message(chat_id, chunk, parse_mode="Markdown", reply_markup=reply_markup)
            return
        except apihelper.ApiTelegramException as error:
            if "can't parse entities" in error.description.lower():
                bot.send_message(chat_id, chunk, reply_markup=reply_markup)
                return
            raise
        except Exception:
            if attempt == 2:
                raise
            _time.sleep(1.0)


def send_pretty_message(chat_id, text, reply_markup=None):
    if not text:
        return
    max_len = 1200
    if len(text) <= max_len:
        _send_single_chunk(chat_id, text, reply_markup=reply_markup)
        return
    parts = []
    remaining = text
    while len(remaining) > max_len:
        split_at = remaining.rfind("\n\n", 0, max_len)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    for idx, part in enumerate(parts):
        if part:
            _send_single_chunk(chat_id, part, reply_markup=reply_markup if idx == len(parts) - 1 else None)
            import time as _t; _t.sleep(0.35)


def download_telegram_file(file_path):
    """Download a Telegram file in small 15KB HTTP Range chunks to bypass ISP throttling on workers.dev."""
    file_url = apihelper.FILE_URL.format(bot.token, file_path)
    chunks = []
    offset = 0
    step = 15360
    while True:
        hdrs = {"Range": f"bytes={offset}-{offset + step - 1}"}
        r = apihelper.requests.get(file_url, headers=hdrs, proxies=apihelper.proxy, timeout=(20, 60))
        if r.status_code not in (200, 206):
            if offset == 0:
                raise RuntimeError(f"Download failed with status {r.status_code}")
            break
        data = r.content
        if not data:
            break
        chunks.append(data)
        if r.status_code == 200 or len(data) < step:
            break
        offset += len(data)
    return b"".join(chunks)

def upload_to_temp_host(jpeg_bytes):
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    # 1. Пробуем catbox.moe с User-Agent
    try:
        r1 = apihelper.requests.post(
            "https://" + "catbox.moe" + "/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": ("image.jpg", jpeg_bytes, "image/jpeg")},
            headers=hdrs,
            timeout=15,
        )
        if r1.status_code == 200 and r1.text.strip().startswith("http"):
            return r1.text.strip()
    except Exception:
        pass
    # 2. Запасной вариант: freeimage.host
    r2 = apihelper.requests.post(
        "https://" + "freeimage.host" + "/api/1/upload?key=6d207e02198a847aa98d0a2a901485a5",
        files={"source": ("image.jpg", jpeg_bytes, "image/jpeg")},
        headers=hdrs,
        timeout=15,
    )
    r2.raise_for_status()
    return r2.json()["image"]["url"]


def build_vision_content(raw_bytes, prompt_text):
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    w, h = img.size
    images_b64 = []

    # Если это длинный телефонный скриншот — нарезаем внахлест на 2-3 крупных фрагмента + общий план
    if h > w * 1.45:
        # Общий вид (чтобы модель видела структуру и рисунки целиком)
        full_copy = img.copy()
        full_copy.thumbnail((1400, 2200))
        b_full = io.BytesIO()
        full_copy.save(b_full, format="JPEG", quality=88)
        images_b64.append(base64.b64encode(b_full.getvalue()).decode("utf-8"))

        # Крупные перекрывающиеся фрагменты сверху вниз
        step = int(h * 0.45)
        slice_h = int(h * 0.58)
        for top in range(0, h - int(h * 0.15), step):
            bottom = min(h, top + slice_h)
            crop = img.crop((0, top, w, bottom))
            b_crop = io.BytesIO()
            crop.save(b_crop, format="JPEG", quality=92)
            images_b64.append(base64.b64encode(b_crop.getvalue()).decode("utf-8"))
    else:
        img.thumbnail((1800, 1800))
        b_single = io.BytesIO()
        img.save(b_single, format="JPEG", quality=90)
        images_b64.append(base64.b64encode(b_single.getvalue()).decode("utf-8"))

    content = [{"type": "text", "text": prompt_text}]
    for b64_item in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_item}", "detail": "high"},
        })
    return content

def compress_image_bytes(raw_bytes, max_side=768, quality=72):
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)
    buf.name = "image.jpg"
    return buf

def generate_and_send_image(user_id, prompt_text):
    send_pretty_message(user_id, "🎨 *Готовлю изображение…*")

    try:
        # Генерируем изображение через GPT image 2.6 в BotHub
        img_response = client.images.generate(
            model="seedream-5-0-flash", prompt=prompt_text, size="1024x1024", n=1
        )

        image_data = img_response.data[0]
        filename = f"gen_{user_id}.png"

        caption_text = f"✨ Готово! Запрос: _{prompt_text}_"
        if getattr(image_data, "b64_json", None):
            photo_buf = compress_image_bytes(base64.b64decode(image_data.b64_json))
            temp_url = upload_to_temp_host(photo_buf.getvalue())
            bot.send_photo(user_id, temp_url, caption=caption_text, parse_mode="Markdown")
            log_usage(user_id, "image_gen", 0)
        elif getattr(image_data, "url", None):
            try:
                bot.send_photo(user_id, image_data.url, caption=caption_text, parse_mode="Markdown")
                log_usage(user_id, "image_gen", 0)
            except Exception:
                resp = apihelper.requests.get(
                    image_data.url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=90,
                )
                resp.raise_for_status()
                with open(filename, "wb") as f:
                    f.write(resp.content)
                with open(filename, "rb") as photo_file:
                    bot.send_photo(user_id, photo_file, caption=caption_text, parse_mode="Markdown")
                os.remove(filename)
        else:
            raise ValueError("Empty image response from API")

    except Exception as e:
        logging.exception(f"Image generation failed for user {user_id}: {e}")
        send_pretty_message(
            user_id,
            "Не получилось подготовить изображение. Попробуй ещё раз "
            "или измени описание.",
        )


@bot.message_handler(commands=["stats"])
def stats_command(message):
    user_id = message.chat.id
    is_admin = (str(user_id) == str(ADMIN_ID)) if ADMIN_ID else True
    NL = chr(10)

    conn = sqlite3.connect("bot_stats.db")
    cur = conn.cursor()

    COST_PER_TOKEN = 0.352
    COST_PER_IMAGE = 16908.77

    if not is_admin:
        cur.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(tokens_used), 0),
                SUM(CASE WHEN action_type = 'image_gen' THEN 1 ELSE 0 END),
                SUM(CASE WHEN action_type = 'vision' THEN 1 ELSE 0 END),
                SUM(CASE WHEN action_type = 'text' THEN 1 ELSE 0 END)
            FROM usage_logs
            WHERE user_id = ? AND action_type != 'visit'
            """,
            (user_id,),
        )
        total_req, u_tokens, img_cnt, vis_cnt, txt_cnt = cur.fetchone()
        conn.close()

        spent_caps = int(round((u_tokens or 0) * COST_PER_TOKEN + (img_cnt or 0) * COST_PER_IMAGE))
        spent_rub = round(spent_caps * 0.0002, 2)

        report = NL.join([
            "✦ *Твоя статистика Yulia AI*",
            "───────────────",
            f"◈ *Запросов выполнено:* {total_req or 0}",
            f"◈ *Потрачено ресурсов:* ~{spent_caps:,} CAPS (~{spent_rub} ₽)",
            "",
            "✧ *По задачам:*",
            f"• Диалоги и поиск: {txt_cnt or 0}",
            f"• Разбор фото и задач: {vis_cnt or 0}",
            f"• Генерация картинок: {img_cnt or 0}",
        ]).replace(",", " ")
        send_pretty_message(user_id, report)
        return

    cur.execute("SELECT value FROM bot_settings WHERE key = 'base_caps'")
    row_caps = cur.fetchone()
    base_caps = float(row_caps.__getitem__(0)) if row_caps else 2521353.0

    cur.execute(
        """
        SELECT
            COUNT(DISTINCT user_id),
            COUNT(*),
            COALESCE(SUM(tokens_used), 0),
            SUM(CASE WHEN action_type = 'image_gen' THEN 1 ELSE 0 END),
            SUM(CASE WHEN action_type = 'vision' THEN 1 ELSE 0 END),
            SUM(CASE WHEN action_type = 'text' THEN 1 ELSE 0 END)
        FROM usage_logs
        WHERE action_type != 'visit'
        """
    )
    uniq_users, total_reqs, total_tokens, img_cnt, vis_cnt, txt_cnt = cur.fetchone()

    cur.execute(
        """
        SELECT
            user_id,
            MAX(username),
            MAX(first_name),
            COUNT(*),
            COALESCE(SUM(tokens_used), 0),
            SUM(CASE WHEN action_type = 'image_gen' THEN 1 ELSE 0 END)
        FROM usage_logs
        WHERE action_type != 'visit'
        GROUP BY user_id
        ORDER BY MAX(id) DESC
        LIMIT 8
        """
    )
    recent_users = cur.fetchall()
    conn.close()

    spent_total = (total_tokens or 0) * COST_PER_TOKEN + (img_cnt or 0) * COST_PER_IMAGE
    rem_caps = max(0, int(round(base_caps - spent_total)))
    rem_rub = round(rem_caps * 0.0002, 2)

    lines = [
        "✦ *Статистика Yulia AI* ✦",
        "──────────────────",
        f"💰 *Точный остаток:* ~{rem_caps:,} CAPS (~{rem_rub} ₽)",
        f"👥 *Активных пользователей:* {uniq_users or 0}",
        f"⚡ *Всего запросов:* {total_reqs or 0}",
        f"🧮 *Токенов учтено:* {total_tokens or 0:,}",
        "",
        "✧ *По типам задач:*",
        f"  🎨 Генерация фото: *{img_cnt or 0}*",
        f"  👁 Разбор фото / скриншотов: *{vis_cnt or 0}*",
        f"  💬 Текст и поиск: *{txt_cnt or 0}*",
        "",
        "✧ *Расход по пользователям:*",
    ]
    if not recent_users:
        lines.append("  • _Пока нет запросов_")
    else:
        for uid, uname, fname, cnt, utok, uimg in recent_users:
            if not fname and not uname:
                try:
                    _c = bot.get_chat(uid)
                    fname = getattr(_c, "first_name", None)
                    uname = getattr(_c, "username", None)
                except Exception:
                    pass
            label = f"@{uname}" if uname else (fname or str(uid))
            u_spent = int(round((utok or 0) * COST_PER_TOKEN + (uimg or 0) * COST_PER_IMAGE))
            u_rub = round(u_spent * 0.0002, 2)
            lines.append(f"  • {label}: {cnt} запр. (~{u_spent:,} CAPS / ~{u_rub} ₽)")

    report = NL.join(lines).replace(",", " ")
    card_buf = build_stats_card(
        rem_caps, rem_rub, uniq_users or 0, total_reqs or 0,
        total_tokens or 0, img_cnt or 0, vis_cnt or 0, txt_cnt or 0
    )
    if card_buf:
        cap_lines = ["*Расход по пользователям:*"]
        if not recent_users:
            cap_lines.append("  • _Пока нет запросов_")
        else:
            for uid, uname, fname, cnt, utok, uimg in recent_users:
                if not fname and not uname:
                    try:
                        _c = bot.get_chat(uid)
                        fname = getattr(_c, 'first_name', None)
                        uname = getattr(_c, 'username', None)
                    except Exception:
                        pass
                label = f'@{uname}' if uname else (fname or str(uid))
                u_spent = int(round((utok or 0) * COST_PER_TOKEN + (uimg or 0) * COST_PER_IMAGE))
                u_rub = round(u_spent * 0.0002, 2)
                cap_lines.append(f'  • {label}: {cnt} запр. (~{u_spent:,} CAPS / ~{u_rub} ₽)')
        caption_txt = NL.join(cap_lines).replace(',', ' ')
        try:
            card_url = upload_to_temp_host(card_buf.getvalue())
            bot.send_photo(user_id, card_url, caption=caption_txt, parse_mode='Markdown')
        except Exception:
                card_buf.seek(0)
                bot.send_photo(user_id, card_buf, caption=caption_txt, parse_mode="Markdown")
        except Exception as _card_err:
            logger.warning("Stats card send failed, fallback to text: %s", _card_err)
            send_pretty_message(user_id, report)
    else:
        send_pretty_message(user_id, report)

@bot.message_handler(commands=["balance"])
def set_balance_command(message):
    if message.chat.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        send_pretty_message(message.chat.id, "Укажи текущий баланс CAPS числом, например: `/balance 2732524`")
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(STATS_DB)
    conn.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('base_caps', ?)", (parts[1],))
    conn.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('base_caps_ts', ?)", (now_str,))
    conn.commit()
    conn.close()
    val_fmt = f"{int(parts[1]):,}".replace(",", " ")
    send_pretty_message(message.chat.id, f"✅ Стартовый баланс зафиксирован: *{val_fmt} CAPS*. Теперь `/stats` будет автоматически считать остаток!")


@bot.message_handler(commands=["start"])
def start_message(message):
    user_id = message.chat.id
    log_usage(user_id, "visit", 0, getattr(message.from_user, "username", None), getattr(message.from_user, "first_name", None))
    try:
        bot.send_photo(user_id, "https://iili.io/oq9QW3g.png")
    except Exception as e:
        logger.warning("Welcome photo failed: %s", e)
    show_welcome(message)


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    user_id = message.chat.id
    bot.send_chat_action(user_id, "typing")
    send_pretty_message(user_id, "🎙 *Распознаю голосовое сообщение…*")

    file_info = bot.get_file(message.voice.file_id)
    downloaded_file = download_telegram_file(file_info.file_path)

    voice_filename = f"voice_{user_id}.ogg"
    with open(voice_filename, "wb") as new_file:
        new_file.write(downloaded_file)

    with open(voice_filename, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1", file=audio_file
        )

    recognized_text = transcript.text
    send_pretty_message(user_id, f"🎤 *Ты сказала:* _{recognized_text}_")
    os.remove(voice_filename)

    answer = ask_claude(user_id, recognized_text)
    if not answer:
        return
    send_pretty_message(user_id, answer)

    bot.send_chat_action(user_id, "record_voice")
    reply_audio_filename = f"reply_{user_id}.ogg"
    selected_voice = user_voices.get(user_id, "nova")

    speech_response = client.audio.speech.create(
        model="tts-1", voice=selected_voice, input=answer, response_format="opus"
    )
    speech_response.stream_to_file(reply_audio_filename)

    with open(reply_audio_filename, "rb") as voice_reply:
        bot.send_voice(user_id, voice_reply)

    os.remove(reply_audio_filename)


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    user_id = message.chat.id
    user_caption = message.caption if message.caption else ""
    if not message.photo:
        send_pretty_message(user_id, "Не удалось получить фотографию. Попробуй отправить её ещё раз.")
        return

    input_filename = f"edit_in_{user_id}.jpg"
    output_filename = f"edit_out_{user_id}.png"

    # Проверяем, просит ли пользователь отредактировать картинку по ключевым словам
    edit_triggers = ("измени", "замени", "убери", "удали", "отредактируй", "сделай", "преврати", "перерисуй", "добавь")
    if user_caption.lower().strip().startswith(edit_triggers):
        try:
            bot.send_chat_action(user_id, "upload_photo")
            send_pretty_message(user_id, "🪄 *Обрабатываю фотографию…*")

            # get_file and the timed download both use the configured Workers proxy.
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_file = download_telegram_file(file_info.file_path)
            if not downloaded_file:
                raise ValueError("Telegram returned an empty photo file")

            with open(input_filename, "wb") as f:
                f.write(downloaded_file)

            # 2. Отправляем фото и задачу в модель GPT Image 2.6 для редактирования
            with open(input_filename, "rb") as image_file:
                edit_response = client.images.edit(
                    model="seedream-5-0-flash",
                    image=image_file,
                    prompt=user_caption,
                    size="1024x1024",
                )

            image_data = edit_response.data[0]

            # 3. Сохраняем готовое фото из ссылки или из base64
            if getattr(image_data, "url", None):
                urllib.request.urlretrieve(image_data.url, output_filename)
            elif getattr(image_data, "b64_json", None):
                with open(output_filename, "wb") as f:
                    f.write(base64.b64decode(image_data.b64_json))
            else:
                raise ValueError("Image API returned neither URL nor image data")

            with open(output_filename, "rb") as out_photo:
                photo_buf = compress_image_bytes(out_photo.read())
            temp_url = upload_to_temp_host(photo_buf.getvalue())
            bot.send_photo(
                user_id,
                temp_url,
                caption=f"✨ Готово! Задача: _{user_caption}_",
                parse_mode="Markdown",
            )
            log_usage(user_id, "image_edit", 0)

        except Exception as e:
            logger.exception("Photo editing failed for user %s: %s", user_id, e)
            try:
                send_pretty_message(
                    user_id,
                    "Не получилось обработать фотографию. Проверь подпись к фото "
                    "и попробуй ещё раз.",
                )
            except Exception:
                logger.exception("Could not notify user %s about photo failure", user_id)
        finally:
            for filename in (input_filename, output_filename):
                try:
                    if os.path.exists(filename):
                        os.remove(filename)
                except OSError:
                    logger.exception("Could not remove temporary file %s", filename)
        return

    # Обычный режим: если триггерных слов нет — просто анализируем картинку
    try:
        bot.send_chat_action(user_id, "typing")
        send_pretty_message(user_id, "🎨 *Обрабатываю фотографию…*")

        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = download_telegram_file(file_info.file_path)
        if not downloaded_file:
            raise ValueError("Telegram returned an empty photo file")
        analysis_prompt = (
            user_caption
            if user_caption
            else "СТРОГО: читай ТОЛЬКО то, что реально видно на фрагментах картинки, ничего не придумывай. Сначала дословно выпиши условие каждой задачи с фото, затем реши. Если на нём есть учебные задачи, тест, формулы, код или текст задания — полностью расшифруй условие каждой задачи и дай подробное пошаговое решение с ответом. Если это обычное фото или схема — подробно опиши и объясни её."
        )

        if user_id not in user_histories:
            user_histories[user_id] = [
                {"role": "system", "content": get_system_prompt()}
            ]

        image_message = build_vision_content(downloaded_file, analysis_prompt)

        response = client.chat.completions.create(
            model=("gemini-2.5-pro" if "олимпиад" in analysis_prompt.lower() else "gemini-2.5-flash"),
            messages=[
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": image_message},
            ],
        )

        used_vis = getattr(getattr(response, "usage", None), "total_tokens", 0)
        log_usage(user_id, "image_vision", used_vis)
        answer = response.choices[0].message.content
        user_histories[user_id].append(
            {"role": "user", "content": f"[Пользователь отправил фото: {analysis_prompt}]"}
        )
        user_histories[user_id].append({"role": "assistant", "content": answer})
        send_pretty_message(user_id, answer)
    except Exception as e:
        logger.exception("Photo analysis failed for user %s: %s", user_id, e)
        try:
            send_pretty_message(
                user_id,
                "Не получилось получить или обработать фотографию. "
                "Проверь соединение и попробуй отправить её ещё раз.",
            )
        except Exception:
            logger.exception("Could not notify user %s about photo failure", user_id)


# Новое: обработка PDF, Word (.docx) и текстовых (.txt) документов
@bot.message_handler(content_types=["document"])
def handle_document(message):
    user_id = message.chat.id
    doc = message.document
    file_name = doc.file_name
    ext = os.path.splitext(file_name)[
        1
    ].lower()  # Узнаём расширение файла (.pdf, .docx, .txt)

    if ext in [".png", ".jpg", ".jpeg", ".webp"]:
        try:
            with keep_typing(user_id, "typing"):
                send_pretty_message(user_id, f"🖼 *Изучаю изображение «{file_name}»…*")
                file_info = bot.get_file(doc.file_id)
                raw_bytes = download_telegram_file(file_info.file_path)
                # Оптимизируем разрешение до 1600px (текст и формулы идеально читаются)
                caption_q = (message.caption or "").strip() or "Внимательно прочитай текст и формулы на изображении и подробно выполни все задания или ответь на вопрос."
                if user_id not in user_histories:
                    user_histories[user_id] = [{"role": "system", "content": get_system_prompt()}]
                img_msg = build_vision_content(raw_bytes, caption_q)
                resp = client.chat.completions.create(
                    model=("gemini-2.5-pro" if "олимпиад" in caption_q.lower() else "gemini-2.5-flash"),
                    messages=[{"role": "system", "content": get_system_prompt()}, {"role": "user", "content": img_msg}],
                )
                used_v = getattr(getattr(resp, "usage", None), "total_tokens", 0)
                log_usage(user_id, "image_vision", used_v, getattr(message.from_user, "username", None), getattr(message.from_user, "first_name", None))
                ans = resp.choices.message.content
                user_histories[user_id].append({"role": "user", "content": f"[Файл-изображение {file_name}: {caption_q}]"})
                user_histories[user_id].append({"role": "assistant", "content": ans})
                send_pretty_message(user_id, ans)
        except Exception as e:
            logger.exception("Image document failed for user %s: %s", user_id, e)
            send_pretty_message(user_id, "⚠️ Не удалось прочитать изображение из файла. Попробуй отправить его ещё раз.")
        return

    if ext not in [".pdf", ".docx", ".txt"]:
        send_pretty_message(
            user_id,
            "Пока я читаю документы PDF, DOCX, TXT и изображения (PNG, JPG, WEBP). "
            "Пришли файл в одном из этих форматов.",
        )
        return

    bot.send_chat_action(user_id, "typing")
    send_pretty_message(user_id, f"📄 *Изучаю документ «{file_name}»…*")

    try:
        # 1. Скачиваем файл из Telegram
        file_info = bot.get_file(doc.file_id)
        downloaded_file = download_telegram_file(file_info.file_path)
        temp_path = f"temp_{user_id}_{file_name}"

        with open(temp_path, "wb") as f:
            f.write(downloaded_file)

        # 2. Извлекаем текст в зависимости от формата
        extracted_text = ""
        if ext == ".pdf":
            reader = PdfReader(temp_path)
            for page in reader.pages:
                extracted_text += (page.extract_text() or "") + "\n"
        elif ext == ".docx":
            word_doc = docx.Document(temp_path)
            for para in word_doc.paragraphs:
                extracted_text += para.text + "\n"
        elif ext == ".txt":
            with open(temp_path, "r", encoding="utf-8") as f:
                extracted_text = f.read()

        os.remove(temp_path)  # Удаляем временный файл с диска

        if not extracted_text.strip():
            send_pretty_message(
                user_id,
                "Не удалось извлечь текст из документа. Возможно, это скан "
                "или файл не содержит текстового слоя.",
            )
            return

        # Ограничиваем объём до 30 000 символов для аккуратной передачи в память
        short_text = extracted_text[:30000]

        # 3. Сохраняем содержимое файла в память диалога пользователя
        if user_id not in user_histories:
            user_histories[user_id] = [
                {"role": "system", "content": get_system_prompt()}
            ]

        user_prompt = (
            message.caption
            if message.caption
            else "Сделай краткую, понятную выжимку из этого документа по пунктам и будь готов отвечать на мои вопросы по нему."
        )
        full_message = f"Пользователь загрузил документ «{file_name}». Вот его содержимое:\n\n{short_text}\n\nЗадание пользователя: {user_prompt}"

        send_pretty_message(user_id, "Формирую ответ…")
        answer = ask_claude(user_id, full_message)
        send_pretty_message(user_id, answer)

    except Exception as e:
        print(f"Document processing failed for user {user_id}: {e}")
        send_pretty_message(
            user_id,
            "Не удалось извлечь текст из этого файла (возможно, внутри только картинки или скан). Попробуй сделать скриншот страницы и отправить его как фото!",
        )


@bot.callback_query_handler(func=lambda call: call.data in ("ask_clear_mem", "show_my_stats"))
def handle_soft_menu_callbacks(call):
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    if call.data == "ask_clear_mem":
        request_memory_clear(call.message.chat.id)
    elif call.data == "show_my_stats":
        stats_command(call.message)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("settings_")
    or call.data in {"confirm_clear", "cancel_clear"}
)
def callback_settings(call):
    user_id = call.message.chat.id

    if call.data == "settings_voice":
        switch_voice_for_user(user_id)
    elif call.data == "settings_clear":
        request_memory_clear(user_id)
    elif call.data == "confirm_clear":
        if user_id in pending_memory_clear:
            clear_memory_confirmed(user_id)
        else:
            send_pretty_message(
                user_id,
                "Запрос на очистку уже закрыт. История разговора не изменена.",
                reply_markup=types.ReplyKeyboardRemove(),
            )
    elif call.data == "cancel_clear":
        pending_memory_clear.discard(user_id)
        send_pretty_message(
            user_id,
            "Очистка отменена. История и настройки сохранены.",
            reply_markup=types.ReplyKeyboardRemove(),
        )

    bot.answer_callback_query(call.id)




@bot.message_handler(content_types=["text"])
def handle_text(message):
    user_id = message.chat.id
    text = (message.text or "").strip()
    if not text:
        return

    img_prompt = extract_image_prompt(text)
    if img_prompt:
        generate_and_send_image(user_id, img_prompt)
        return

    bot.send_chat_action(user_id, "typing")
    answer = ask_claude(user_id, text)
    send_pretty_message(user_id, answer)


print("Мультимодальный бот с генерацией картинок запущен!")
while True:
    try:
        apihelper.proxy = {"https": "socks5h://127.0.0.1:1080", "http": "socks5h://127.0.0.1:1080"}
        telebot.apihelper.CONNECT_TIMEOUT = 20
        telebot.apihelper.READ_TIMEOUT = 60
        bot.polling(none_stop=True, interval=1.0, timeout=45, long_polling_timeout=25)
    except Exception as _pe:
        logger.warning("Polling reconnect: %s", _pe)
        import time as _pt; _pt.sleep(0.5)
