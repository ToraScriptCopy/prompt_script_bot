#!/usr/bin/env python3
"""
tg_prompt_script_bot.py

IMPORTANT: Do NOT put your real Telegram token directly into files
that will be uploaded to public repos. Use environment variables or
your hosting provider's secret storage.

This script reads token from the environment variable TG_TOKEN.
If you want to run locally and prefer a .env file, see README.txt.
"""
import os
import logging
from typing import List
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSING_LANG, CHOOSING_PLATFORM, INPUT_DESC, INPUT_SCENES, INPUT_DURATION, CONFIRM = range(6)

PLATFORMS = [
    "Sora", "Deepseek", "ChatGPT", "Gemini", "Veo 3", "Veo 3.1", "Llama 3"
]

PLATFORM_TEMPLATES = {
    "default": "{scene_brief}\\n\\nStyle: {style}\\nDuration: {duration}s\\nDetails: {details}",
    "Sora": "[Sora Prompt]\\n{scene_brief}\\n--visual style: {style}\\n--duration: {duration}s\\n--details: {details}",
    "Deepseek": "<Deepseek>\\nPROMPT: {scene_brief} | STYLE: {style} | DURATION: {duration}s | DETAILS: {details}",
    "ChatGPT": "You are generating a structured visual prompt for an image/video model.\\nScene: {scene_brief}\\nStyle: {style}\\nDuration: {duration}s\\nExtra details: {details}",
    "Gemini": "Gemini-style prompt:\\n{scene_brief}\\nVisualStyle={style}; Duration={duration}s; Notes={details}",
    "Veo 3": "[Veo v3]\\n{scene_brief}\\nSTYLE:{style}\\nDUR:{duration}s\\nNOTE:{details}",
    "Veo 3.1": "[Veo v3.1]\\n{scene_brief}\\n--style={style}\\n--duration={duration}s\\n--notes={details}",
    "Llama 3": "Llama-structured prompt:\\n- Scene: {scene_brief}\\n- Visual style: {style}\\n- Duration: {duration}s\\n- Details: {details}",
}

STYLE_SUGGESTIONS = {
    "ru": ["реалистично", "киношное освещение", "аниме", "арт-хаус", "ретро 80s", "киберпанк", "фэнтези"],
    "en": ["photorealistic", "cinematic lighting", "anime", "art-house", "retro 80s", "cyberpunk", "fantasy"],
}

def keyboard_from_list(items: List[str], row_size=2):
    keys = []
    for i in range(0, len(items), row_size):
        row = [InlineKeyboardButton(text=x, callback_data=x) for x in items[i:i+row_size]]
        keys.append(row)
    return InlineKeyboardMarkup(keys)

def split_into_scenes(desc: str, n_scenes: int) -> List[str]:
    import re
    sentences = re.split(r'(?<=[.!?])\\s+', desc.strip())
    if len(sentences) >= n_scenes:
        per = max(1, len(sentences) // n_scenes)
        scenes = []
        i = 0
        while len(scenes) < n_scenes and i < len(sentences):
            chunk = " ".join(sentences[i:i+per]).strip()
            scenes.append(chunk)
            i += per
        while len(scenes) < n_scenes:
            scenes.append("A continuation of the scene.")
        return scenes[:n_scenes]
    else:
        if len(desc) < 50:
            return [desc + f" — detail {i+1}" for i in range(n_scenes)]
        chunk_len = max(20, len(desc) // n_scenes)
        scenes = [desc[i:i+chunk_len].strip() for i in range(0, len(desc), chunk_len)]
        while len(scenes) < n_scenes:
            scenes.append("A bridging visual scene.")
        return scenes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Русский", callback_data="lang_ru"), InlineKeyboardButton("English", callback_data="lang_en")]
    ])
    await update.message.reply_text("Привет! Выбери язык / Choose language:", reply_markup=kb)
    return CHOOSING_LANG

async def lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = "ru" if q.data == "lang_ru" else "en"
    context.user_data["lang"] = lang
    await q.edit_message_text(text=("Выбран русский — теперь выбери платформу:" if lang=="ru" else "Language set — choose platform:"),
                              reply_markup=keyboard_from_list(PLATFORMS, row_size=2))
    return CHOOSING_PLATFORM

async def platform_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    platform = q.data
    context.user_data["platform"] = platform
    lang = context.user_data.get("lang", "ru")
    text = ("Напиши краткое описание идеи (что ты хочешь видеть):" if lang=="ru" else "Send a short description of the idea (what you want to see):")
    await q.edit_message_text(text)
    return INPUT_DESC

async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    context.user_data["description"] = desc
    lang = context.user_data.get("lang", "ru")
    await update.message.reply_text(("Сколько сцен нужно? Введи целое число, например: 8" if lang=="ru" else "How many scenes? Send an integer, e.g. 8"))
    return INPUT_SCENES

async def receive_scenes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    lang = context.user_data.get("lang", "ru")
    try:
        n = int(text)
        if n <= 0 or n > 100:
            raise ValueError
    except Exception:
        await update.message.reply_text(("Введите корректное число сцен (1-100)." if lang=="ru" else "Please send a valid number of scenes (1-100)."))
        return INPUT_SCENES
    context.user_data["n_scenes"] = n
    await update.message.reply_text(("Сколько секунд длится каждая сцена? Введи целое число (например 10), или 'var' для вариативной длительности."
                                    if lang=="ru" else
                                    "Duration in seconds for each scene? Send an integer (e.g. 10), or 'var' for variable durations."))
    return INPUT_DURATION

async def receive_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    lang = context.user_data.get("lang", "ru")
    if text == 'var':
        context.user_data["duration_mode"] = "var"
        context.user_data["duration_value"] = None
    else:
        try:
            d = int(text)
            if d <= 0 or d > 600:
                raise ValueError
            context.user_data["duration_mode"] = "fixed"
            context.user_data["duration_value"] = d
        except Exception:
            await update.message.reply_text(("Введите корректное время (1-600) или 'var'." if lang=="ru" else "Please send a valid duration (1-600) or 'var'."))
            return INPUT_DURATION

    platform = context.user_data.get("platform")
    n = context.user_data.get("n_scenes")
    desc = context.user_data.get("description")
    dur_mode = context.user_data.get("duration_mode")
    dur = context.user_data.get("duration_value")
    confirm_text = (f"Готовлю {n} сцен(ы) для платформы {platform}.\\nОписание: {desc}\\n"
                    f"Длительность: {'вариативная' if dur_mode=='var' else str(d)+'s'}\\n\\nНажми /generate"
                    if lang=="ru"
                    else
                    f"Preparing {n} scenes for platform {platform}.\\nDescription: {desc}\\n"
                    f"Duration: {'variable' if dur_mode=='var' else str(d)+'s'}\\n\\nSend /generate")
    await update.message.reply_text(confirm_text)
    return CONFIRM

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = context.user_data
    platform = user.get("platform", "default")
    n = user.get("n_scenes", 5)
    desc = user.get("description", "An idea")
    dur_mode = user.get("duration_mode", "fixed")
    dur_val = user.get("duration_value", 5)
    lang = user.get("lang", "ru")

    scenes = split_into_scenes(desc, n)

    import random
    durations = [dur_val]*n if dur_mode == "fixed" else [random.randint(4, 15) for _ in range(n)]

    styles = STYLE_SUGGESTIONS.get(lang, STYLE_SUGGESTIONS["ru"])
    template = PLATFORM_TEMPLATES.get(platform, PLATFORM_TEMPLATES["default"])

    out_lines = [f"=== Generated prompts for {platform} ==="]
    for i, scene_brief in enumerate(scenes):
        scene_idx = i + 1
        style = styles[i % len(styles)]
        details = f"Scene {scene_idx} derived from user idea. Add camera moves, close-ups as needed."
        duration = durations[i]
        prompt_text = template.format(scene_brief=scene_brief, style=style, details=details, duration=duration)
        out_lines.append(f"Scene {scene_idx}/{n} — {duration}s")
        out_lines.append(prompt_text)
        out_lines.append("---")

    full = "\\n".join(out_lines)
    CHUNK_SIZE = 3800
    for i in range(0, len(full), CHUNK_SIZE):
        await update.message.reply_text(full[i:i+CHUNK_SIZE])
    return ConversationHandler.END

def main():
    # Read token from environment variable TG_TOKEN (recommended).
    token = os.getenv("TG_TOKEN", "PASTE_YOUR_TOKEN_HERE")
    if token == "PASTE_YOUR_TOKEN_HERE":
        logger.warning("TG_TOKEN not set. Replace the placeholder or set TG_TOKEN in env.")
    app = ApplicationBuilder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_LANG: [CallbackQueryHandler(lang_choice, pattern=r"^lang_")],
            CHOOSING_PLATFORM: [CallbackQueryHandler(platform_choice)],
            INPUT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description)],
            INPUT_SCENES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_scenes)],
            INPUT_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_duration)],
            CONFIRM: [CommandHandler('generate', generate)],
        },
        fallbacks=[CommandHandler('cancel', lambda u,c: ConversationHandler.END)],
    )

    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
