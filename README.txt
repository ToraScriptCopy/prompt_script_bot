Prompt Script Bot

IMPORTANT: For security, DO NOT commit your Telegram token to a public repository.

Files:
- tg_prompt_script_bot.py  -- main bot code (reads TG_TOKEN from environment)
- requirements.txt        -- python dependencies

Quick local run (Linux/macOS):
1) Create a virtual env (recommended):
   python -m venv venv
   source venv/bin/activate
2) Install:
   pip install -r requirements.txt
3) Set your Telegram token as environment variable:
   export TG_TOKEN="YOUR_TELEGRAM_TOKEN"
4) Run:
   python tg_prompt_script_bot.py

Windows (cmd):
   set TG_TOKEN=YOUR_TELEGRAM_TOKEN
   python tg_prompt_script_bot.py

Replit:
- Add TG_TOKEN in Secrets (Environment variables) in Replit GUI.

Render:
- Add TG_TOKEN in Environment -> Environment Variables in the Render service settings.

If you really want to hardcode the token for local testing (NOT RECOMMENDED),
open tg_prompt_script_bot.py and replace PASTE_YOUR_TOKEN_HERE with your token.
But DON'T push that to GitHub.

If you need, I can also generate a small deployment guide for Render/Replit with exact steps.
