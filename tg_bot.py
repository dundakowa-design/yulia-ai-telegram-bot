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
apihelper.CONNECT_TIMEOUT = 10
apihelper.READ_TIMEOUT = 60

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("tg_bot")

load_dotenv()

bot = telebot.TeleBot(os.getenv("TELEGRAM_TOKEN"))
client = OpenAI(
    api_key=os.getenv("BOTHUB_API_KEY"), base_url="https://openai.bothub.chat/v1"
)

user_histories = {}
user_voices = {}  # Храним выбранный голос для каждого пользователя
user_roles = {}  # Храним выбранную роль для каждого пользователя

ROLES = {
    "default": {
        "name": "🤖 Обычный помощник",
        "prompt": "Ты стильный, дружелюбный и умный мультимодальный ИИ-ассистент. Отвечай понятно, по делу и помогай во всех вопросах.",
    },
    "it": {
        "name": "💻 Программирование и IT",
        "prompt": "Ты опытный Python-разработчик и наставник по AI-инженерии. Объясняй код простыми словами сверху вниз, помогай находить ошибки и пиши чистые примеры.",
    },
    "study": {
        "name": "📚 Учёба и наука",
        "prompt": "Ты терпеливый репетитор и методист. Объясняй сложные темы на простых жизненных примерах, делай понятные конспекты и проверяй знания.",
    },
    "text": {
        "name": "✍️ Тексты и документы",
        "prompt": "Ты профессиональный редактор и аналитик. Пиши живые, грамотные тексты, структурируй документы и делай чёткие выжимки без воды.",
    },
    "creative": {
        "name": "🎨 Творчество и хобби",
        "prompt": "Ты креативный соавтор. Помогай придумывать сценарии, стихи, идеи для хобби, игр, подарков и творческих проектов.",
    },
    "lifestyle": {
        "name": "🌿 Кулинария и лайфстайл",
        "prompt": "Ты дружелюбный помощник по образу жизни и кулинарии. Подсказывай вкусные рецепты (в том числе для аэрогриля), идеи для уюта дома и полезные привычки.",
    },
}

user_documents = {}  # Здесь будем хранить текст последнего загруженного документа
waiting_for_image_prompt = (
    set()
)  # Запоминаем пользователей, которые нажали кнопку рисования
pending_memory_clear = set()  # Подтверждение очистки памяти

MAIN_MENU_LABELS = {
    "✨ Помощник",
    "🎨 Фото и дизайн",
    "🎙 Голос",
    "📄 Документы",
    "🎭 Режим",
    "⚙️ Настройки",
}

LEGACY_MENU_LABELS = {
    "✨ Что ты умеешь?": "✨ Помощник",
    "🎨 Нарисовать картинку": "🎨 Фото и дизайн",
    "🎙 Сменить голос": "🎙 Голос",
    "🎭 Сменить роль": "🎭 Режим",
}


def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(
        types.KeyboardButton("✨ Помощник"),
        types.KeyboardButton("🎨 Фото и дизайн"),
    )
    keyboard.row(
        types.KeyboardButton("🎙 Голос"),
        types.KeyboardButton("📄 Документы"),
    )
    keyboard.row(
        types.KeyboardButton("🎭 Режим"),
        types.KeyboardButton("⚙️ Настройки"),
    )
    return keyboard


def get_roles_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton(text=info["name"], callback_data=f"role_{key}")
        for key, info in ROLES.items()
    ]
    keyboard.add(*buttons)
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
    elif section == "🎭 Режим":
        current_role = ROLES[user_roles.get(chat_id, "default")]["name"]
        send_pretty_message(
            chat_id,
            f"🎭 *Текущий режим:* {current_role}\n\nВыбери подходящий режим:",
            reply_markup=get_roles_keyboard(),
        )
    elif section == "⚙️ Настройки":
        role_name = ROLES[user_roles.get(chat_id, "default")]["name"]
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
            f"Режим: {role_name}\n"
            f"Голос ответа: {voice_name}\n\n"
            "Здесь можно сменить голос или начать новый разговор.",
            reply_markup=keyboard,
        )


def show_welcome(message, is_new_user=False):
    user_id = message.chat.id
    if user_id not in user_histories:
        user_histories[user_id] = [
            {"role": "system", "content": get_system_prompt(user_id)}
        ]

    if is_new_user:
        welcome_text = (
            "✨ *Добро пожаловать в Yulia AI*\n\n"
            "Я — твой внимательный помощник для вопросов, идей и повседневных задач.\n\n"
            "Напиши сообщение, отправь голосовое, фото или документ — "
            "а нужный раздел выбери в меню ниже."
        )
    else:
        welcome_text = (
            "✨ *Рада тебя видеть!*\n"
            "Продолжим разговор или откроем нужный раздел?"
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
        "Это удалит текущий контекст переписки. Настройки роли и голоса сохранятся.",
        reply_markup=keyboard,
    )


def get_system_prompt(user_id):
    today = datetime.now().strftime("%d.%m.%Y, время %H:%M")
    role_key = user_roles.get(user_id, "default")
    role_instruction = ROLES[role_key]["prompt"]
    return f"""{role_instruction}
Сегодняшняя дата и время: {today}.
Оформляй ответы красиво: используй *одинарные звёздочки* для жирного шрифта, списки и эмодзи. Никогда не используй решётки ## или ### для заголовков."""


def ask_claude(user_id, user_text):
    if user_id not in user_histories:
        user_histories[user_id] = [
            {"role": "system", "content": get_system_prompt(user_id)}
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
def generate_and_send_image(user_id, prompt_text):
    bot.send_chat_action(user_id, "upload_photo")
    send_pretty_message(user_id, "🎨 *Готовлю изображение…*")

    try:
        # Генерируем изображение через GPT image 2.6 в BotHub
        img_response = client.images.generate(
            model="gpt-image-2.6", prompt=prompt_text, size="1024x1024", n=1
        )

        image_data = img_response.data[0]
        filename = f"gen_{user_id}.png"

        # Если сервер вернул ссылку (url) — скачиваем картинку по ссылке
        if getattr(image_data, "url", None):
            urllib.request.urlretrieve(image_data.url, filename)
        # Если вернул сразу в коде base64 — сохраняем из base64
        elif getattr(image_data, "b64_json", None):
            with open(filename, "wb") as f:
                f.write(base64.b64decode(image_data.b64_json))

        with open(filename, "rb") as photo_file:
            bot.send_photo(
                user_id,
                photo_file,
                caption=f"✨ Готово! Запрос: _{prompt_text}_",
                parse_mode="Markdown",
            )

        os.remove(filename)

    except Exception as e:
        print(f"Image generation failed for user {user_id}: {e}")
        send_pretty_message(
            user_id,
            "Не получилось подготовить изображение. Попробуй ещё раз "
            "или измени описание.",
        )


@bot.message_handler(commands=["start"])
def start_message(message):
    user_id = message.chat.id
    waiting_for_image_prompt.discard(user_id)
    show_welcome(message, is_new_user=user_id not in user_histories)


@bot.message_handler(commands=["help"])
def help_message(message):
    user_id = message.chat.id
    waiting_for_image_prompt.discard(user_id)
    if user_id not in user_histories:
        user_histories[user_id] = [
            {"role": "system", "content": get_system_prompt(user_id)}
        ]
    send_pretty_message(
        user_id,
        "✨ *Чем могу помочь*\n"
        "Задавай вопросы, отправляй голосовые сообщения и фото, "
        "создавай или редактируй изображения, присылай PDF, DOCX и TXT.\n\n"
        "Выбери раздел в меню или просто продолжи переписку.",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(commands=["clear"])
def clear_memory(message):
    user_id = message.chat.id
    request_memory_clear(user_id)


def clear_memory_confirmed(chat_id):
    user_histories[chat_id] = [
        {"role": "system", "content": get_system_prompt(chat_id)}
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

    # Совместимость со старыми подписями клавиатуры.
    if text == "🎨 Нарисовать картинку":
        waiting_for_image_prompt.add(user_id)
        send_pretty_message(
            user_id,
            "🎨 *Опиши изображение, которое хочешь создать.*\n"
            "Например: уютная оранжерея в мягком утреннем свете.",
        )
        return
    elif text == "🎙 Сменить голос":
        waiting_for_image_prompt.discard(user_id)
        switch_voice(message)
        return

    section = LEGACY_MENU_LABELS.get(text, text)
    if section in MAIN_MENU_LABELS:
        waiting_for_image_prompt.discard(user_id)
        if section == "✨ Помощник" and text == "✨ Что ты умеешь?":
            show_welcome(message)
        else:
            show_section(user_id, section)
        return

    if text == "🧹 Очистить память":
        waiting_for_image_prompt.discard(user_id)
        clear_memory(message)
        return
    # Если пользователь до этого нажал кнопку «Нарисовать картинку»
    if user_id in waiting_for_image_prompt:
        waiting_for_image_prompt.remove(user_id)
        generate_and_send_image(user_id, text)
        return

    # Если пользователь просто начал фразу со слова «нарисуй»
    if text.lower().startswith("нарисуй "):
        prompt_text = text[8:].strip()  # Отрезаем слово «нарисуй »
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

    # Если голосом попросили нарисовать картинку!
    if recognized_text.lower().startswith("нарисуй "):
        generate_and_send_image(user_id, recognized_text[8:].strip())
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
    edit_triggers = ("измени", "замени", "убери", "удали", "отредактируй", "сделай фон")
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
                    model="gpt-image-2.6",
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
                bot.send_photo(
                    user_id,
                    out_photo,
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

        file_info = bot.get_file(message.photo[-1].file_id)
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
                {"role": "system", "content": get_system_prompt(user_id)}
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
                {"role": "system", "content": get_system_prompt(user_id)}
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("role_"))
def callback_role(call):
    user_id = call.message.chat.id
    waiting_for_image_prompt.discard(user_id)
    role_key = call.data.replace("role_", "")
    user_roles[user_id] = role_key
    if user_id not in user_histories:
        user_histories[user_id] = [
            {"role": "system", "content": get_system_prompt(user_id)}
        ]
    else:
        user_histories[user_id][0] = {
            "role": "system",
            "content": get_system_prompt(user_id),
        }

    role_name = ROLES[role_key]["name"]
    bot.answer_callback_query(call.id, f"Выбрана роль: {role_name}")
    send_pretty_message(
        user_id,
        f"✅ *Режим изменён:* {role_name}\nКонтекст разговора сохранён.",
        reply_markup=get_main_keyboard(),
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
