import os
import base64
from pypdf import PdfReader
import docx
import urllib.request
from datetime import datetime
import telebot
from telebot import apihelper, types  # Добавили types для создания кнопок
from dotenv import load_dotenv
from openai import OpenAI

apihelper.API_URL = "https://tg-proxy.dundakowa.workers.dev/bot{0}/{1}"
apihelper.FILE_URL = "https://tg-proxy.dundakowa.workers.dev/file/bot{0}/{1}"

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


# Обновлённая клавиатура с кнопкой генерации картинок
def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("✨ Что ты умеешь?")
    btn2 = types.KeyboardButton("🎨 Нарисовать картинку")
    btn3 = types.KeyboardButton("🧹 Очистить память")
    btn4 = types.KeyboardButton("🎙 Сменить голос")
    btn5 = types.KeyboardButton("🎭 Сменить роль")
    keyboard.add(btn1, btn2)
    keyboard.add(btn3, btn4, btn5)
    return keyboard


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
    except Exception:
        bot.send_message(chat_id, text, reply_markup=reply_markup)


# Новое: функция генерации и отправки картинки
def generate_and_send_image(user_id, prompt_text):
    bot.send_chat_action(user_id, "upload_photo")
    send_pretty_message(user_id, "🎨 *Рисую картинку, подожди 10–15 секунд...*")

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
        send_pretty_message(user_id, f"⚠️ Не удалось создать картинку. Ошибка: `{e}`")


@bot.message_handler(commands=["start", "help"])
def start_message(message):
    user_id = message.chat.id
    user_histories[user_id] = [
        {"role": "system", "content": get_system_prompt(user_id)}
    ]

    welcome_text = (
        "✨ *Привет! Я твой персональный ИИ-ассистент*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Я работаю на базе *GPT 6 Luna* и умею:\n\n"
        "💬 *Понимать текст* и помнить контекст нашего диалога\n"
        "🎨 *Рисовать картинки* — нажми кнопку снизу или напиши «Нарисуй...»\n"
        "🎤 *Слушать голосовые* и отвечать тебе живым голосом\n"
        "👁 *Анализировать фото* — присылай скриншоты, документы или любые снимки\n"
        "📄 *Читать PDF и Word* — присылай документы для анализа и выжимок\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 *Выбери действие на панели снизу или просто напиши мне!*"
    )

    send_pretty_message(user_id, welcome_text, reply_markup=get_main_keyboard())


@bot.message_handler(commands=["clear"])
def clear_memory(message):
    user_id = message.chat.id
    user_histories[user_id] = [
        {"role": "system", "content": get_system_prompt(user_id)}
    ]
    send_pretty_message(
        user_id,
        "🧹 *Память очищена!* Начинаем разговор с чистого листа.",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(commands=["voice"])
def switch_voice(message):
    user_id = message.chat.id
    current = user_voices.get(user_id, "nova")
    new_voice = "onyx" if current == "nova" else "nova"
    user_voices[user_id] = new_voice
    voice_name = "Мужской (Onyx)" if new_voice == "onyx" else "Женский (Nova)"
    send_pretty_message(
        user_id,
        f"🎙 Голос озвучки переключён на: *{voice_name}*",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(content_types=["text"])
def handle_text(message):
    user_id = message.chat.id
    text = message.text

    if text == "✨ Что ты умеешь?":
        start_message(message)
        return
    elif text == "🧹 Очистить память":
        clear_memory(message)
        return
    elif text == "🎙 Сменить голос":
        switch_voice(message)
        return
    elif text == "🎨 Нарисовать картинку":
        waiting_for_image_prompt.add(user_id)
        send_pretty_message(
            user_id,
            "🖌 *Опиши словами, что именно нужно нарисовать?* (Например: _футуристичный сад на закате в стиле Pixar_)",
        )
        return
    elif text == "🎭 Сменить роль":
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [
            types.InlineKeyboardButton(text=info["name"], callback_data=f"role_{key}")
            for key, info in ROLES.items()
        ]
        markup.add(*buttons)
        current_role = ROLES[user_roles.get(user_id, "default")]["name"]
        send_pretty_message(
            user_id,
            f"🎭 *Текущий режим:* {current_role}\n\nВыбери новую роль для бота:",
            reply_markup=markup,
        )
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
    answer = ask_claude(user_id, text)
    send_pretty_message(user_id, answer)


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    user_id = message.chat.id
    bot.send_chat_action(user_id, "typing")

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

    # Проверяем, просит ли пользователь отредактировать картинку по ключевым словам
    edit_triggers = ("измени", "замени", "убери", "удали", "отредактируй", "сделай фон")
    if user_caption.lower().strip().startswith(edit_triggers):
        bot.send_chat_action(user_id, "upload_photo")
        send_pretty_message(
            user_id, "🪄 *Редактирую фотографию, подожди 10–15 секунд...*"
        )

        try:
            # 1. Скачиваем исходное фото на диск во временный файл
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            input_filename = f"edit_in_{user_id}.png"
            output_filename = f"edit_out_{user_id}.png"

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

            with open(output_filename, "rb") as out_photo:
                bot.send_photo(
                    user_id,
                    out_photo,
                    caption=f"✨ Готово! Задача: _{user_caption}_",
                    parse_mode="Markdown",
                )

            # Удаляем оба временных файла
            os.remove(input_filename)
            os.remove(output_filename)

        except Exception as e:
            if os.path.exists(f"edit_in_{user_id}.png"):
                os.remove(f"edit_in_{user_id}.png")
            send_pretty_message(
                user_id, f"⚠️ Не удалось отредактировать фото. Ошибка: `{e}`"
            )
        return

    # Обычный режим: если триггерных слов нет — просто анализируем картинку
    bot.send_chat_action(user_id, "typing")
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
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
        messages=user_histories[user_id] + [{"role": "user", "content": image_message}],
    )

    answer = response.choices[0].message.content
    user_histories[user_id].append(
        {"role": "user", "content": f"[Пользователь отправил фото: {analysis_prompt}]"}
    )
    user_histories[user_id].append({"role": "assistant", "content": answer})

    send_pretty_message(user_id, answer)


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
            "⚠️ Пока я умею читать только файлы форматов *PDF*, *Word (.docx)* и *TXT*.",
        )
        return

    bot.send_chat_action(user_id, "typing")
    send_pretty_message(user_id, f"📄 *Читаю документ «{file_name}»...*")

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
                "⚠️ Не удалось найти текст в этом файле (возможно, это скан в виде картинки).",
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

        answer = ask_claude(user_id, full_message)
        send_pretty_message(user_id, answer)

    except Exception as e:
        send_pretty_message(user_id, f"⚠️ Ошибка при чтении файла: `{e}`")


@bot.callback_query_handler(func=lambda call: call.data.startswith("role_"))
def callback_role(call):
    user_id = call.message.chat.id
    role_key = call.data.replace("role_", "")
    user_roles[user_id] = role_key
    user_histories[user_id] = [
        {"role": "system", "content": get_system_prompt(user_id)}
    ]

    role_name = ROLES[role_key]["name"]
    bot.answer_callback_query(call.id, f"Выбрана роль: {role_name}")
    send_pretty_message(
        user_id,
        f"✅ *Режим переключён на:* {role_name}\nПамять обновлена под новую задачу!",
    )


print("Мультимодальный бот с генерацией картинок запущен!")
bot.infinity_polling(timeout=60, long_polling_timeout=60)
