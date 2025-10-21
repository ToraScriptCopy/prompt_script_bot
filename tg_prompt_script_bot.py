#!/usr/bin/env python3
"""
tg_prompt_script_bot_v3.py

Features:
- Clickable menu (no need to type /start; any message will show the menu)
- Rich inline-menu flow for creating prompts (language -> platform -> description -> scenes -> duration)
- "Mini-AI" local enhancer (heuristic) and optional Deepseek API integration (if DEEPSEEK_API_KEY is set)
- Commands: /menu, /generate (if flow completed), /improve, /export, /settings
- Export prompts as ZIP with prompts.json
Security:
- DO NOT hardcode TG_TOKEN or DEEPSEEK_API_KEY into files that will be uploaded publicly.
- Set environment variables on your host (Render/Replit/VPS): TG_TOKEN and optionally DEEPSEEK_API_KEY.

How to run:
1) pip install -r requirements.txt
2) export TG_TOKEN="your_telegram_token"
   export DEEPSEEK_API_KEY="your_deepseek_token"   # optional
3) python tg_prompt_script_bot_v3.py
"""
import os
import logging
import json
import random
import zipfile
import io
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

import requests
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
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config ---
PLATFORMS = [
    "ChatGPT","Gemini","Llama 3","Veo 3","Veo 3.1","Sora","Deepseek","Midjourney",
    "Stable Diffusion","DALL·E","Runway","Imagen","Claude","Perplexity","BlueWillow",
    "DreamStudio","InvokeAI","ControlNet","Deforum","CustomModel","Mistral","Falcon",
    "Anthropic","OpenJourney","Ernie-ViLG","GLIDE","Kandinsky","Pika","Poe","Grok"
]

LANGUAGES = {
    "ru":"Русский","en":"English","es":"Español","fr":"Français","de":"Deutsch",
    "it":"Italiano","pt":"Português","nl":"Nederlands","pl":"Polski","sv":"Svenska",
    "no":"Norsk","da":"Dansk","fi":"Suomi","cs":"Čeština","hu":"Magyar","ro":"Română",
    "tr":"Türkçe","ja":"日本語","ko":"한국어","zh":"中文"
}

STYLE_POOL = [
    "photorealistic","cinematic lighting","anime","art-house","retro 80s","cyberpunk",
    "fantasy","painterly","surreal","documentary","hyper-detailed","low-poly"
]
MOOD_POOL = ["tense","dreamy","melancholic","uplifting","ominous","hopeful","mysterious","whimsical"]

# Per-user session storage (in-memory)
SESSIONS: Dict[int, Dict[str, Any]] = {}

# Utility: main menu keyboard
def main_menu_kb():
    kb = [
        [InlineKeyboardButton("Create Prompts", callback_data="menu_create"),
         InlineKeyboardButton("Improve Last", callback_data="menu_improve")],
        [InlineKeyboardButton("Export", callback_data="menu_export"),
         InlineKeyboardButton("Settings", callback_data="menu_settings")]
    ]
    return InlineKeyboardMarkup(kb)

# Utility: keyboard from list
def keyboard_from_list(items: List[str], row_size=2):
    rows=[]
    for i in range(0,len(items),row_size):
        rows.append([InlineKeyboardButton(text=x, callback_data=f"pick|{x}") for x in items[i:i+row_size]])
    return InlineKeyboardMarkup(rows)

# --- Mini-AI enhancer (local heuristics) ---
def mini_ai_enhance(scene_short: str) -> Dict[str,str]:
    title = scene_short.strip()[:48].rstrip(" .,!?:;") + ("..." if len(scene_short.strip())>48 else "")
    style = random.choice(STYLE_POOL)
    mood = random.choice(MOOD_POOL)
    camera = random.choice(["close-up","wide shot","tracking shot","slow zoom","overhead","dolly in"])
    color = random.choice(["neon blues and magentas","warm golden hour tones","muted earth tones","high-contrast monochrome","pastel palette"])
    adjective = random.choice(["soft","harsh","glowing","muted","vibrant","textured","grainy","pristine"])
    expanded = (
        f"{scene_short}. Details: {adjective} surfaces, {color}. "
        f"Ambience cues: distant hum, soft wind. Lighting: {style} with a {mood} tone. "
        f"Suggested shot: {camera}. Add subtle particle effects and depth-of-field."
    )
    # basic sanitization: remove very explicit violent verbs
    for bad in ["разстрелять","убить","убивают","shoot","kill"]:
        expanded = expanded.replace(bad, "[removed]")
    return {"title": title, "brief": expanded, "style": style, "mood": mood, "camera": camera, "color": color}

# --- Deepseek integration helper (optional) ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # set this in env if you want remote polishing
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://aimlapi.com/app/api")  # user can override if needed

def call_deepseek_polish(prompt_text: str) -> str:
    """
    Polishes the prompt_text via Deepseek (if API key provided).
    This is a best-effort wrapper. The exact endpoint/path may differ depending on provider.
    We send a JSON POST with {"prompt": "..."} and Authorization header.
    If the API call fails, we return the original prompt_text.
    """
    if not DEEPSEEK_API_KEY:
        return prompt_text
    try:
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        payload = {"prompt": prompt_text}
        resp = requests.post(DEEPSEEK_API_URL, json=payload, headers=headers, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            # try common keys
            if isinstance(data, dict):
                for key in ("result","output","polished","text"):
                    if key in data and isinstance(data[key], str) and data[key].strip():
                        return data[key].strip()
            # fallback: if response is text
            if isinstance(data, str):
                return data
        else:
            logger.warning("Deepseek API returned status %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.exception("Deepseek call failed: %s", e)
    return prompt_text

# --- Flow handlers ---
async def ensure_session(user_id:int):
    if user_id not in SESSIONS:
        SESSIONS[user_id] = {"state":"idle","last_prompts":[]}

async def any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Reply to any non-command message with a friendly menu (so user doesn't have to type /start).
    """
    user_id = update.effective_user.id
    await ensure_session(user_id)
    await update.message.reply_text("Main Menu — выбери действие / choose action:", reply_markup=main_menu_kb())

# Menu callback handler
async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await ensure_session(user_id)
    data = query.data

    if data == "menu_create":
        # start create flow: choose language
        await query.edit_message_text("Choose language / Выберите язык:", reply_markup=keyboard_from_list([f\"{k} — {v}\" for k,v in LANGUAGES.items()], row_size=2))
        SESSIONS[user_id]["state"] = "choosing_language"
        return
    if data == "menu_improve":
        # run improve on last prompts
        session = SESSIONS[user_id]
        if not session.get("last_prompts"):
            await query.edit_message_text("No prompts generated yet. Create first.")
            return
        # apply local improvements
        for p in session["last_prompts"]:
            p["prompt"] += "\\n--IMPROVED: add cinematic grain; try 24fps; experimental color swap"
            p["meta"]["improved"] = True
        await query.edit_message_text("Prompts improved locally. Use Export to download or /improve for remote polish.")
        return
    if data == "menu_export":
        session = SESSIONS[user_id]
        if not session.get("last_prompts"):
            await query.edit_message_text("No prompts to export. Create first.")
            return
        # create zip in-memory and send
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("prompts.json", json.dumps(session, ensure_ascii=False, indent=2))
        buf.seek(0)
        await query.edit_message_text("Exporting prompts.zip...")
        await context.bot.send_document(chat_id=user_id, document=InputFile(buf, filename="prompts.zip"))
        return
    if data == "menu_settings":
        keys = []
        keys.append([InlineKeyboardButton("Toggle Deepseek (env)", callback_data="setting|deepseek")])
        keys.append([InlineKeyboardButton("Back to Menu", callback_data="menu_back")])
        await query.edit_message_text("Settings:", reply_markup=InlineKeyboardMarkup(keys))
        return
    if data == "menu_back":
        await query.edit_message_text("Main Menu:", reply_markup=main_menu_kb())
        return

    # Picking language / platform flow
    if data.startswith("pick|"):
        pick = data.split("|",1)[1]
        user_session = SESSIONS[user_id]
        state = user_session.get("state")
        if state == "choosing_language":
            # store language code (format "ru — Русский")
            lang_code = pick.split(" — ")[0]
            user_session["language"] = lang_code
            user_session["state"] = "choosing_platform"
            await query.edit_message_text("Language set to %s. Now choose platform:" % pick, reply_markup=keyboard_from_list(PLATFORMS, row_size=2))
            return
        if state == "choosing_platform":
            user_session["platform"] = pick
            user_session["state"] = "awaiting_description"
            await query.edit_message_text("Platform set to %s. Send a short description of your idea (one sentence):" % pick)
            return

    # fallback
    await query.edit_message_text("Unhandled menu action. Back to main menu.", reply_markup=main_menu_kb())

# Message handler for collecting description, scenes, duration
async def message_collector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await ensure_session(user_id)
    user_session = SESSIONS[user_id]
    state = user_session.get("state","idle")
    text = update.message.text.strip()
    if state == "awaiting_description":
        user_session["description"] = text
        user_session["state"] = "awaiting_scenes"
        await update.message.reply_text("Got it. How many scenes? (e.g. 6)")
        return
    if state == "awaiting_scenes":
        try:
            n = int(text)
            if n < 1 or n > 200:
                raise ValueError()
        except:
            await update.message.reply_text("Please send a valid number between 1 and 200.")
            return
        user_session["n_scenes"] = n
        user_session["state"] = "awaiting_duration"
        await update.message.reply_text("Duration per scene in seconds (number) or 'var' for variable durations:")
        return
    if state == "awaiting_duration":
        if text.lower() == "var":
            user_session["duration_mode"] = "var"
            user_session["duration_value"] = None
        else:
            try:
                d = int(text)
                if d < 1 or d > 3600: raise ValueError()
                user_session["duration_mode"] = "fixed"
                user_session["duration_value"] = d
            except:
                await update.message.reply_text("Send integer seconds (1-3600) or 'var'.")
                return
        # ready to generate
        await update.message.reply_text("Generating prompts... (this may take a couple seconds)")
        prompts = generate_prompts_for_session(user_id)
        user_session["last_prompts"] = prompts
        user_session["state"] = "idle"
        # send short list summary
        lines = [f"Generated {len(prompts)} prompts for {user_session.get('platform')}:"]
        for p in prompts:
            lines.append(f"- Scene {p['index']}: {p['meta']['title']} ({p['duration']}s)")
        await update.message.reply_text("\\n".join(lines))
        await update.message.reply_text("Use the menu to Improve or Export. Or click /improve for remote polish.")
        return
    # default: show menu
    await update.message.reply_text("Main Menu:", reply_markup=main_menu_kb())

# Prompt generation logic
def split_into_scenes(desc: str, n_scenes:int) -> List[str]:
    import re
    desc = desc.strip()
    if not desc:
        return [f"Scene {i+1}" for i in range(n_scenes)]
    sents = re.split(r'(?<=[.!?])\\s+', desc)
    if len(sents) >= n_scenes:
        per = max(1, len(sents)//n_scenes)
        scenes=[]
        i=0
        while len(scenes) < n_scenes and i < len(sents):
            scenes.append(" ".join(sents[i:i+per]).strip())
            i += per
        while len(scenes) < n_scenes:
            scenes.append("A continuing visual scene.")
        return scenes[:n_scenes]
    clauses = re.split(r',\\s*', desc)
    if len(clauses) >= n_scenes:
        per = max(1, len(clauses)//n_scenes)
        scenes=[]
        i=0
        while len(scenes) < n_scenes and i < len(clauses):
            scenes.append(", ".join(clauses[i:i+per]).strip())
            i += per
        while len(scenes) < n_scenes:
            scenes.append("A bridging visual scene.")
        return scenes[:n_scenes]
    # fallback
    chunk = max(30, len(desc)//n_scenes)
    parts = [desc[i:i+chunk].strip() for i in range(0,len(desc),chunk)]
    if len(parts) >= n_scenes:
        return parts[:n_scenes]
    while len(parts) < n_scenes:
        parts.append("A bridging visual scene.")
    return parts

def generate_prompts_for_session(user_id:int) -> List[Dict[str,Any]]:
    session = SESSIONS[user_id]
    desc = session.get("description","An idea")
    n = session.get("n_scenes",4)
    dur_mode = session.get("duration_mode","fixed")
    dur_val = session.get("duration_value",6)
    platform = session.get("platform","CustomModel")
    scenes_short = split_into_scenes(desc, n)
    prompts=[]
    for i,s in enumerate(scenes_short):
        meta = mini_ai_enhance(s)
        duration = dur_val if dur_mode=="fixed" else random.randint(3,15)
        template = (
            "{title}\\n{brief}\\nStyle: {style}\\nMood: {mood}\\nCamera: {camera}\\nDuration: {duration}s\\nNegative: {negative}\\nNotes: auto-generated"
        )
        prompt_text = template.format(
            title=meta["title"],
            brief=meta["brief"],
            style=meta["style"],
            mood=meta["mood"],
            camera=meta["camera"],
            duration=duration,
            negative="avoid text, logos, watermarks"
        )
        # if remote Deepseek available, attempt polishing (best-effort, non-blocking)
        polished = call_deepseek_polish(prompt_text) if DEEPSEEK_API_KEY else prompt_text
        prompts.append({
            "index": i+1,
            "duration": duration,
            "platform": platform,
            "prompt": polished,
            "meta": meta
        })
    return prompts

# /improve command -> try remote polish (Deepseek) if key present
async def cmd_improve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await ensure_session(user_id)
    session = SESSIONS[user_id]
    if not session.get("last_prompts"):
        await update.message.reply_text("No prompts to improve. Create first.")
        return
    if not DEEPSEEK_API_KEY:
        await update.message.reply_text("No remote API key configured. Improved locally instead.")
        # local improvement
        for p in session["last_prompts"]:
            p["prompt"] += "\\n--LOCAL_IMPROVE: add cinematic color grade and subtle film grain."
        await update.message.reply_text("Local improvements applied. Use Export to download.")
        return
    # Remote polishing loop
    await update.message.reply_text("Polishing prompts with Deepseek...")
    for p in session["last_prompts"]:
        try:
            polished = call_deepseek_polish(p["prompt"])
            p["prompt_remote"] = polished
        except Exception as e:
            logger.exception("Polish failed: %s", e)
    await update.message.reply_text("Remote polishing finished. Use /export to download JSON/ZIP.")

# /export command
async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await ensure_session(user_id)
    session = SESSIONS[user_id]
    if not session.get("last_prompts"):
        await update.message.reply_text("No prompts to export.")
        return
    # create zip in-memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("prompts.json", json.dumps(session, ensure_ascii=False, indent=2))
    buf.seek(0)
    await update.message.reply_document(document=InputFile(buf, filename="prompts_export.zip"))

# /settings command shows info and instructions to set DEEPSEEK_API_KEY
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "Settings & Tips:",
        "• To enable remote polishing (Deepseek), set environment variable DEEPSEEK_API_KEY with your token.",
        "• Example (Linux): export DEEPSEEK_API_KEY=\"your_token_here\"",
        "• The bot will never store your token in the exported prompts.json.",
        "• To change Telegram token, update TG_TOKEN in your host."
    ]
    await update.message.reply_text("\\n".join(lines))

# Start the bot and handlers
def main():
    token = os.getenv("TG_TOKEN", "PASTE_YOUR_TOKEN_HERE")
    if token == "PASTE_YOUR_TOKEN_HERE":
        logger.warning("TG_TOKEN not set. Set it in the environment before running.")
    app = ApplicationBuilder().token(token).build()
    # Handlers
    app.add_handler(CallbackQueryHandler(menu_router))
    app.add_handler(CommandHandler("menu", lambda u,c: c.bot.send_message(chat_id=u.effective_chat.id, text="Main Menu:", reply_markup=main_menu_kb())))
    app.add_handler(CommandHandler("improve", cmd_improve))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("settings", cmd_settings))
    # Any normal message triggers the menu (so user doesn't have to type /start)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_message))
    # Message collector for the interactive flow (description/scenes/duration)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_collector))
    app.run_polling()

if __name__ == "__main__":
    main()
