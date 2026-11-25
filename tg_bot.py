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
apihelper.API_URL = "https://tg-proxy.dundakowa.workers.dev/bot{0}/{1}"
# TeleBot formats file downloads through FILE_URL using the same bot token and
# file_path returned by get_file (e.g. /file/bot<TOKEN>/<file_path>).
apihelper.FILE_URL = "https://tg-proxy.dundakowa.workers.dev/file/bot{0}/{1}"
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
            reply_markup=get_main_keyboard(),
        )
    elif section == "🎨 Фото и дизайн":
        send_pretty_message(
            chat_id,
            "🎨 *Фото и дизайн*\n"
            "Создать изображение — напиши «Нарисуй…» и опиши идею.\n"
            "Изменить фотографию — пришли её с подписью, например «Убери фон».\n"
            "Обсудить изображение — просто отправь фото с вопросом или без него.",
            reply_markup=get_main_keyboard(),
        )
    elif section == "🎙 Голос":
        voice = user_voices.get(chat_id, "nova")
        voice_name = "Мужской (Onyx)" if voice == "onyx" else "Женский (Nova)"
        send_pretty_message(
            chat_id,
            "🎙 *Голосовое общение*\n"
            "Отправь голосовое сообщение — я распознаю речь, отвечу и озвучу ответ.\n\n"
            f"Текущий голос озвучки: *{voice_name}*. Переключить его можно в настройках.",
            reply_markup=get_main_keyboard(),
        )
    elif section == "📄 Документы":
        send_pretty_message(
            chat_id,
            "📄 *Документы*\n"
            "Пришли PDF, DOCX или TXT — я помогу разобраться с содержимым "
            "и подготовлю краткую выжимку.\n\n"
            "Если у тебя есть конкретный вопрос или пожелание, добавь его к файлу.",
            reply_markup=get_main_keyboard(),
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


def show_welcome(message, is_new_user=False):
    user_id = message.chat.id
    if user_id not in user_histories:
        user_histories[user_id] = [
            {"role": "system", "content": get_system_prompt()}
        ]

    if is_new_user:
        welcome_text = (
            "✨ *Привет! Я Yulia AI*\n\n"
            "Помогу с вопросами и идеями, создам или отредактирую фото, "
            "проанализирую изображение или документ, распознаю голосовое "
            "и озвучу ответ. Просто напиши или отправь файл."
        )
    else:
        welcome_text = (
            "✨ *Рада тебя видеть!*\n"
            "Продолжим разговор? Напиши сообщение или отправь фото, документ "
            "или голосовое."
        )

    send_pretty_message(user_id, welcome_text, reply_markup=get_main_keyboard())


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


def get_system_prompt():
    today = datetime.now().strftime("%d.%m.%Y, время %H:%M")
    return f"""Ты — Yulia AI, персональный мультимодальный ИИ-ассистент в Telegram. Всегда представляйся только как Yulia AI; никогда не называй себя ChatGPT или OpenAI.
Автоматически определяй задачу пользователя: написание или отладка кода, работа с текстом, аналитика, обучение, творчество или бытовой вопрос. Самостоятельно выбирай наиболее подходящий стиль и глубину ответа — переключать режимы не нужно. Для кода давай точные, работающие решения; для обучения объясняй понятно; для аналитики структурируй выводы; для текстов учитывай цель и аудиторию; для творчества предлагай оригинальные идеи; на бытовые вопросы отвечай практично и дружелюбно. Учитывай контекст переписки и содержимое присланных изображений и документов.
Сегодняшняя дата и время: {today}.
Оформляй ответы понятно: используй *одинарные звёздочки* для жирного шрифта, списки и эмодзи, когда это уместно. Не используй решётки ## или ### для заголовков."""


def ask_claude(user_id, user_text):
    if user_id not in user_histories:
        user_histories[user_id] = [
            {"role": "system", "content": get_system_prompt()}
        ]

    user_histories[user_id].append({"role": "user", "content": user_text})

    response = client.chat.completions.create(
        model="gpt-6-luna", messages=user_histories[user_id]
    )

    answer = response.choices[0].message.content
    user_histories[user_id].append({"role": "assistant", "content": answer})
    return answer


def send_pretty_message(chat_id, text, reply_markup=None):
    try:
        bot.send_message(
            chat_id, text, parse_mode="Markdown", reply_markup=reply_markup
        )
    except apihelper.ApiTelegramException as error:
        if "can't parse entities" not in error.description.lower():
            raise
        bot.send_message(chat_id, text, reply_markup=reply_markup)


def download_telegram_file(file_path):
    """Download a Telegram file via the configured proxy with bounded timeouts."""
    file_url = apihelper.FILE_URL.format(bot.token, file_path)
    response = apihelper.requests.get(
        file_url,
        timeout=(apihelper.CONNECT_TIMEOUT, apihelper.READ_TIMEOUT),
        proxies=apihelper.proxy,
    )
    if response.status_code != 200:
        raise apihelper.ApiHTTPException("Download file", response)
    return response.content


# Новое: функция генерации и отправки картинки
from PIL import Image
import io

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


def compress_image_bytes(raw_bytes, max_side=768, quality=72):
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)
    buf.name = "image.jpg"
    return buf

def generate_and_send_image(user_id, prompt_text):
    bot.send_chat_action(user_id, "upload_photo")
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
        elif getattr(image_data, "url", None):
            try:
                bot.send_photo(user_id, image_data.url, caption=caption_text, parse_mode="Markdown")
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


@bot.message_handler(commands=["start"])
def start_message(message):
    user_id = message.chat.id
    show_welcome(message, is_new_user=user_id not in user_histories)


@bot.message_handler(commands=["help"])
def help_message(message):
    user_id = message.chat.id
    if user_id not in user_histories:
        user_histories[user_id] = [
            {"role": "system", "content": get_system_prompt()}
        ]
    send_pretty_message(
        user_id,
        "✨ *Чем могу помочь*\n"
        "Умный диалог с памятью, генерация и редактирование фото, "
        "анализ изображений и документов, голосовой ввод и озвучка ответов.\n\n"
        "Просто напиши сообщение или отправь фото, голосовое либо документ.",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(commands=["clear"])
def clear_memory(message):
    user_id = message.chat.id
    request_memory_clear(user_id)


def clear_memory_confirmed(chat_id):
    user_histories[chat_id] = [
        {"role": "system", "content": get_system_prompt()}
    ]
    pending_memory_clear.discard(chat_id)
    send_pretty_message(
        chat_id,
        "🧹 *История очищена.* Настройки сохранены — можем начать новый разговор.",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(commands=["voice"])
def switch_voice(message):
    user_id = message.chat.id
    switch_voice_for_user(user_id)


def switch_voice_for_user(user_id):
    current = user_voices.get(user_id, "nova")
    new_voice = "onyx" if current == "nova" else "nova"
    user_voices[user_id] = new_voice
    voice_name = "Мужской (Onyx)" if new_voice == "onyx" else "Женский (Nova)"
    send_pretty_message(
        user_id,
        f"🎙 *Голос ответа изменён:* {voice_name}",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(content_types=["text"])
def handle_text(message):
    user_id = message.chat.id
    text = message.text

    if text == "🎙 Сменить голос":
        switch_voice(message)
        return

    section = LEGACY_MENU_LABELS.get(text, text)
    if section in MAIN_MENU_LABELS:
        if section == "✨ Помощник" and text == "✨ Что ты умеешь?":
            show_welcome(message)
        else:
            show_section(user_id, section)
        return

    if text == "🧹 Очистить память":
        clear_memory(message)
        return

    prompt_text = extract_image_prompt(text)
    if prompt_text is not None:
        if not prompt_text:
            send_pretty_message(
                user_id,
                "🎨 Опиши изображение, которое хочешь создать — например, "
                "«Нарисуй уютную оранжерею в мягком утреннем свете».",
            )
            return
        generate_and_send_image(user_id, prompt_text)
        return

    bot.send_chat_action(user_id, "typing")
    send_pretty_message(user_id, "Формирую ответ…")
    answer = ask_claude(user_id, text)
    send_pretty_message(user_id, answer)


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    user_id = message.chat.id
    bot.send_chat_action(user_id, "typing")
    send_pretty_message(user_id, "🎙 *Распознаю голосовое сообщение…*")

    file_info = bot.get_file(message.voice.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

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

    prompt_text = extract_image_prompt(recognized_text)
    if prompt_text is not None:
        if not prompt_text:
            send_pretty_message(user_id, "Опиши, какое изображение нужно создать.")
            return
        generate_and_send_image(user_id, prompt_text)
        return

    send_pretty_message(user_id, "Формирую ответ…")
    answer = ask_claude(user_id, recognized_text)
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
            file_info = bot.get_file(message.photo[0].file_id)
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

        file_info = bot.get_file(message.photo[0].file_id)
        downloaded_file = download_telegram_file(file_info.file_path)
        if not downloaded_file:
            raise ValueError("Telegram returned an empty photo file")
        base64_image = base64.b64encode(downloaded_file).decode("utf-8")

        analysis_prompt = (
            user_caption
            if user_caption
            else "Подробно и красиво опиши, что изображено на этой картинке."
        )

        if user_id not in user_histories:
            user_histories[user_id] = [
                {"role": "system", "content": get_system_prompt()}
            ]

        image_message = [
            {"type": "text", "text": analysis_prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
            },
        ]

        response = client.chat.completions.create(
            model="gpt-6-luna",
            messages=user_histories[user_id]
            + [{"role": "user", "content": image_message}],
        )

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

    if ext not in [".pdf", ".docx", ".txt"]:
        send_pretty_message(
            user_id,
            "Пока я читаю документы PDF, DOCX и TXT. "
            "Пришли файл в одном из этих форматов.",
        )
        return

    bot.send_chat_action(user_id, "typing")
    send_pretty_message(user_id, f"📄 *Изучаю документ «{file_name}»…*")

    try:
        # 1. Скачиваем файл из Telegram
        file_info = bot.get_file(doc.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
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
            "Не получилось прочитать документ. Проверь файл и попробуй отправить его ещё раз.",
        )


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
                reply_markup=get_main_keyboard(),
            )
    elif call.data == "cancel_clear":
        pending_memory_clear.discard(user_id)
        send_pretty_message(
            user_id,
            "Очистка отменена. История и настройки сохранены.",
            reply_markup=get_main_keyboard(),
        )

    bot.answer_callback_query(call.id)


print("Мультимодальный бот с генерацией картинок запущен!")
bot.infinity_polling(timeout=10, long_polling_timeout=20)
