#!/usr/bin/env python3
"""
tg_prompt_script_bot_v2.py

Improved version:
- 20 platforms
- 20 languages
- Better scene splitting and "mini-AI" local enhancer (no external API)
- Export to JSON/ZIP with prompts and metadata (/export)
- /improve to enhance generated prompts using built-in heuristics
- Safe: reads TG_TOKEN from environment; DO NOT hardcode your token.

Usage:
- /start to begin
- pick language & platform
- send description, number of scenes, duration (or 'var')
- /generate to build prompts
- /improve to enhance last generated prompts
- /export to receive a ZIP with prompts.json
"""
import os
import logging
import json
import random
from typing import List, Dict
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
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

# States
(
    CHOOSING_LANG,
    CHOOSING_PLATFORM,
    INPUT_DESC,
    INPUT_SCENES,
    INPUT_DURATION,
    CONFIRM
) = range(6)

# 20 platforms (mix of real and common model names)
PLATFORMS = [
    "ChatGPT", "Gemini", "Llama 3", "Veo 3", "Veo 3.1", "Sora", "Deepseek",
    "Midjourney", "Stable Diffusion", "DALL·E", "Runway", "Imagen",
    "Claude", "Perplexity", "BlueWillow", "DreamStudio", "InvokeAI",
    "ControlNet", "Deforum", "CustomModel"
]

# 20 languages (language code -> display)
LANGUAGES = {
    "ru": "Русский", "en": "English", "es": "Español", "fr": "Français",
    "de": "Deutsch", "it": "Italiano", "pt": "Português", "nl": "Nederlands",
    "pl": "Polski", "sv": "Svenska", "no": "Norsk", "da": "Dansk",
    "fi": "Suomi", "cs": "Čeština", "hu": "Magyar", "ro": "Română",
    "tr": "Türkçe", "ja": "日本語", "ko": "한국어", "zh": "中文"
}

# Platform-specific templates (improved)
PLATFORM_TEMPLATES = {
    "default": "{scene_title}\n{scene_brief}\nStyle: {style}\nMood: {mood}\nCamera: {camera}\nDuration: {duration}s\nAspect: {aspect}\nNegative: {negative}\nNotes: {details}",
}
# Give each platform a variant; many reuse the same structure but with small syntax differences
for p in PLATFORMS:
    PLATFORM_TEMPLATES[p] = PLATFORM_TEMPLATES["default"].replace("Notes:", f"Notes ({p}):")

# Style & mood suggestions
STYLE_POOL = ["photorealistic","cinematic lighting","anime","art-house","retro 80s","cyberpunk","fantasy","painterly","surreal","documentary"]
MOOD_POOL = ["tense","dreamy","melancholic","uplifting","ominous","hopeful","mysterious","whimsical"]

# Mini-AI enhancer: simple heuristics to expand a short scene into richer description
ADJECTIVES = ["soft", "harsh", "glowing", "muted", "vibrant", "washed-out", "textured", "slick", "grainy", "pristine"]
CAMERA_MOVES = ["close-up", "wide shot", "pan right", "pan left", "tracking shot", "dolly in", "dolly out", "overhead", "slow zoom"]
COLOR_PALETTES = ["neon blues and magentas","warm golden hour tones","muted earth tones","high-contrast monochrome","pastel palette"]

# Helpers
def keyboard_from_list(items: List[str], row_size=2):
    keys=[]
    for i in range(0,len(items),row_size):
        row=[InlineKeyboardButton(text=str(x), callback_data=str(x)) for x in items[i:i+row_size]]
        keys.append(row)
    return InlineKeyboardMarkup(keys)

def split_into_scenes(desc: str, n_scenes: int) -> List[str]:
    # Improved splitting: try sentences, fallback to clauses and balanced chunks
    import re
    desc = desc.strip()
    if not desc:
        return [f"Scene placeholder {i+1}" for i in range(n_scenes)]
    sentences = re.split(r'(?<=[.!?])\s+', desc)
    # If too many sentences, group them
    if len(sentences) >= n_scenes:
        per = max(1, len(sentences)//n_scenes)
        scenes=[]
        i=0
        while len(scenes)<n_scenes and i<len(sentences):
            scenes.append(" ".join(sentences[i:i+per]).strip())
            i+=per
        while len(scenes)<n_scenes:
            scenes.append("A continuing visual scene.")
        return scenes[:n_scenes]
    # If fewer sentences, split by commas/clauses
    clauses = re.split(r',\s*', desc)
    if len(clauses) >= n_scenes:
        per = max(1, len(clauses)//n_scenes)
        scenes=[]
        i=0
        while len(scenes)<n_scenes and i<len(clauses):
            scenes.append(", ".join(clauses[i:i+per]).strip())
            i+=per
        while len(scenes)<n_scenes:
            scenes.append("A bridging visual scene.")
        return scenes[:n_scenes]
    # fallback: equal-length chunks
    chunk_len = max(30, len(desc)//n_scenes)
    scenes = [desc[i:i+chunk_len].strip() for i in range(0, len(desc), chunk_len)]
    if len(scenes) >= n_scenes:
        return scenes[:n_scenes]
    while len(scenes)<n_scenes:
        scenes.append("A bridging visual scene.")
    return scenes

def mini_ai_enhance(scene_short: str) -> Dict[str,str]:
    # Produce structured enhanced scene metadata
    title = scene_short[:40].rstrip(" .,!?:;") + ("..." if len(scene_short)>40 else "")
    style = random.choice(STYLE_POOL)
    mood = random.choice(MOOD_POOL)
    camera = random.choice(CAMERA_MOVES)
    color = random.choice(COLOR_PALETTES)
    adjective = random.choice(ADJECTIVES)
    # Expand description with sensory detail heuristics
    expanded = (
        f"{scene_short}. Visual details: {adjective} textures, {color}. "
        f"Focus on movement and emotion; include sound cues: subtle ambience and distant echoes. "
        f"Lighting: {style} with {mood} undertone. "
        f"Shot suggestions: {camera}, include a brief close-up to capture expression."
    )
    # safety: simple cleanup of explicit violent words
    expanded = expanded.replace("разстрелять","[violence removed]")
    return {
        "scene_title": title,
        "scene_brief": expanded,
        "style": style,
        "mood": mood,
        "camera": camera,
        "color": color
    }

# Session storage (per-user last generation)
USER_SESSIONS = {}

# Bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = keyboard_from_list([f"{code} — {name}" for code,name in LANGUAGES.items()], row_size=2)
    await update.message.reply_text("Привет! Выбери язык / Choose language:", reply_markup=kb)
    return CHOOSING_LANG

async def lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    # data format "ru — Русский"
    code = data.split(" — ")[0]
    context.user_data["lang"] = code
    # ask platform
    await q.edit_message_text(text=("Язык выбран. Теперь выбери платформу:" if code=='ru' else "Language set. Choose a platform:"),
                              reply_markup=keyboard_from_list(PLATFORMS, row_size=2))
    return CHOOSING_PLATFORM

async def platform_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    platform = q.data
    context.user_data["platform"] = platform
    lang = context.user_data.get("lang","ru")
    await q.edit_message_text(("Напиши краткое описание идеи (коротко):" if lang=='ru' else "Send a short description of the idea:"))
    return INPUT_DESC

async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    context.user_data["description"] = desc
    lang = context.user_data.get("lang","ru")
    await update.message.reply_text(("Сколько сцен нужно? Введи число, например 6" if lang=='ru' else "How many scenes? Send a number, e.g. 6"))
    return INPUT_SCENES

async def receive_scenes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    lang = context.user_data.get("lang","ru")
    try:
        n = int(text)
        if n<=0 or n>200:
            raise ValueError
    except Exception:
        await update.message.reply_text(("Введите корректное число сцен (1-200)." if lang=='ru' else "Please send a valid number of scenes (1-200)."))
        return INPUT_SCENES
    context.user_data["n_scenes"] = n
    await update.message.reply_text(("Длительность каждой сцены в секундах (число) или 'var' для вариативной длительности:" if lang=='ru' else "Duration per scene in seconds (number) or 'var' for variable durations:"))
    return INPUT_DURATION

async def receive_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    lang = context.user_data.get("lang","ru")
    if text == 'var':
        context.user_data["duration_mode"] = "var"
        context.user_data["duration_value"] = None
    else:
        try:
            d = int(text)
            if d<=0 or d>3600:
                raise ValueError
            context.user_data["duration_mode"] = "fixed"
            context.user_data["duration_value"] = d
        except Exception:
            await update.message.reply_text(("Введите корректное время (1-3600) или 'var'." if lang=='ru' else "Please send a valid duration (1-3600) or 'var'."))
            return INPUT_DURATION

    platform = context.user_data.get("platform")
    n = context.user_data.get("n_scenes")
    desc = context.user_data.get("description")
    confirm = (f"Готово: {n} сцен для {platform}. Описание: {desc}. Длительность: {'вариативная' if context.user_data['duration_mode']=='var' else str(context.user_data['duration_value'])+'s'}\nОтправь /generate"
               if context.user_data.get("lang","ru")=='ru'
               else f"Ready: {n} scenes for {platform}. Description: {desc}. Duration: {'variable' if context.user_data['duration_mode']=='var' else str(context.user_data['duration_value'])+'s'}\nSend /generate")
    await update.message.reply_text(confirm)
    return CONFIRM

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = context.user_data
    platform = user.get("platform","CustomModel")
    n = user.get("n_scenes",5)
    desc = user.get("description","An idea")
    dur_mode = user.get("duration_mode","fixed")
    dur_val = user.get("duration_value",5)
    lang = user.get("lang","ru")

    scenes_short = split_into_scenes(desc, n)
    # generate structured scenes using mini_ai_enhance
    scenes=[]
    for s in scenes_short:
        meta = mini_ai_enhance(s)
        scenes.append(meta)
    # durations
    if dur_mode=="fixed":
        durations=[dur_val]*n
    else:
        durations=[random.randint(max(1, int(0.5*dur_val or 4)), max(4, int(2* (dur_val or 10)))) if dur_val else random.randint(4,15) for _ in range(n)]
    # build prompts
    template = PLATFORM_TEMPLATES.get(platform, PLATFORM_TEMPLATES["default"])
    prompts=[]
    for i,meta in enumerate(scenes):
        duration = durations[i]
        aspect="16:9"
        negative = "avoid text overlays; avoid logos; avoid watermarks"
        details = f"Scene {i+1}/{n}. Auto-generated enhancements applied."
        prompt = template.format(
            scene_title=meta["scene_title"],
            scene_brief=meta["scene_brief"],
            style=meta["style"],
            mood=meta["mood"],
            camera=meta["camera"],
            duration=duration,
            aspect=aspect,
            negative=negative,
            details=details
        )
        prompts.append({
            "index": i+1,
            "duration": duration,
            "aspect": aspect,
            "platform": platform,
            "prompt": prompt,
            "meta": meta
        })
    # store in session
    USER_SESSIONS[user_id] = {
        "generated_at": datetime.utcnow().isoformat()+"Z",
        "platform": platform,
        "language": lang,
        "description": desc,
        "prompts": prompts
    }
    # send summaries (short)
    out_lines=[f"=== Generated {len(prompts)} prompts for {platform} ==="]
    for p in prompts:
        out_lines.append(f"Scene {p['index']}/{len(prompts)} — {p['duration']}s — {p['meta']['scene_title']}")
    # send as messages (chunk safe)
    full = "\\n".join(out_lines)
    CHUNK=3800
    for i in range(0,len(full),CHUNK):
        await update.message.reply_text(full[i:i+CHUNK])
    await update.message.reply_text(("/improve — улучшить промпты\\n/export — получить ZIP с prompts.json"
                                    if lang=='ru' else "/improve — enhance prompts\\n/export — download ZIP with prompts.json"))
    return ConversationHandler.END

async def improve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = USER_SESSIONS.get(user_id)
    if not session:
        await update.message.reply_text("No generated prompts found. Generate first with /generate." if context.user_data.get("lang","ru")!="ru" else "Нет сгенерированных промптов. Сначала используй /generate.")
        return
    # enhance each prompt further by adding camera cues, negative prompts, and variants
    for p in session["prompts"]:
        p["prompt"] += "\\n--VARIATION: swap color palette to " + random.choice(COLOR_PALETTES)
        p["prompt"] += "\\n--HINT: try 24fps for cinematic feel; seed=random"
        p["meta"]["enhanced"] = True
    await update.message.reply_text(("Prompts improved and annotated. Use /export to download." if context.user_data.get("lang","ru")!="ru" else "Промпты улучшены и аннотированы. Используй /export для скачивания."))
    return

async def export_prompts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = USER_SESSIONS.get(user_id)
    if not session:
        await update.message.reply_text("No prompts to export. Run /generate first." if context.user_data.get("lang","ru")!="ru" else "Нет промптов для экспорта. Сначала /generate.")
        return
    # create JSON and ZIP
    base_dir = Path("/tmp") / f"prompt_export_{user_id}"
    base_dir.mkdir(parents=True, exist_ok=True)
    json_path = base_dir / "prompts.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    zip_path = base_dir / "prompts_export.zip"
    import zipfile
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(json_path, arcname="prompts.json")
    # send zip
    await update.message.reply_document(document=InputFile(str(zip_path)), filename="prompts_export.zip")
    return

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. /start to begin again." if context.user_data.get("lang","ru")!="ru" else "Отменено. /start чтобы начать заново.")
    return ConversationHandler.END

# Main
from pathlib import Path
def main():
    token = os.getenv("TG_TOKEN", "PASTE_YOUR_TOKEN_HERE")
    if token == "PASTE_YOUR_TOKEN_HERE":
        logger.warning("TG_TOKEN not set. Set it in environment for the bot to work.")
    app = ApplicationBuilder().token(token).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_LANG: [CallbackQueryHandler(lang_choice)],
            CHOOSING_PLATFORM: [CallbackQueryHandler(platform_choice)],
            INPUT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description)],
            INPUT_SCENES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_scenes)],
            INPUT_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_duration)],
            CONFIRM: []
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("generate", generate))
    app.add_handler(CommandHandler("improve", improve))
    app.add_handler(CommandHandler("export", export_prompts))
    app.add_handler(CommandHandler("cancel", cancel))
    app.run_polling()

if __name__ == "__main__":
    main()
