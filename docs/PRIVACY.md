# Privacy

Short version: **your bank data never leaves your computer.** Even with a cloud AI turned on, the AI only ever sees merchant names and your typed questions — never amounts, dates, balances, or the file itself.

## What goes where

| Mode | Your CSV file | Amounts, dates, balances | Merchant names | Your typed questions |
|---|---|---|---|---|
| 🔒 No AI | Stays on your PC | Stay on your PC | Stay on your PC | Stay on your PC |
| 💻 AI on my computer (Ollama) | Stays on your PC | Stay on your PC | Sent to Ollama *on your own PC* | Sent to Ollama *on your own PC* |
| ☁️ OpenAI / Gemini | Stays on your PC | Stay on your PC | **Sent to that company** (only names the built-in rules couldn't place, only when you click the AI button, and never person-to-person payees like Zelle/Venmo names) | **Sent to that company** |

The pill in the top-right corner shows which mode is on. So does the privacy line on the import screen.

## What the app stores on your computer

All in one folder: `~/.money_mirror/`

- `money.db` — your transactions, the cleaned merchant names, the categories, and the category rules you taught it. Only your user account can read this file.
- `config.json` — your settings. If you typed in an API key, it is here too. Only your user account can read this file.

Delete the folder and everything is gone. Or use **Settings → Delete everything**.

## What the app never does

- It never connects to your bank. There is no login, no account linking, no screen scraping.
- It never uploads your file anywhere. The file is read in memory on your PC.
- It has no tracking. No analytics. No crash reports. It never "phones home."
- It listens only on `127.0.0.1`. Other computers on your network cannot reach it.

## How we check this

- One automated test blocks every network connection, then loads the dashboard and asks a question in No-AI mode. If the app tried to reach the internet, that test would fail.
- Another test runs the AI path with a fake AI and inspects every prompt sent to it. It checks that no dollar amount, no transaction date, and no person-to-person payee name appears in any of them. Merchant names are also scrubbed of numbers before they are stored.
- A third test checks that a web page in another browser tab cannot send data into the app (cross-site request guard).
- In No-AI mode the app opens no network connection at all, not even to look for Ollama (it only looks when you open Settings).

See `tests/smoke/test_api.py`.

## Cloud mode: what the AI company sees

If you choose OpenAI or Gemini: a list of merchant names (like "Blue Bottle Coffee") when you click **Let the AI name them**, and the text of your questions (like "how much on coffee since June"). Nothing else. Read their privacy policy. "No AI" and "AI on my computer" modes are always there as fully private choices.

## Keys

API keys live only in `config.json` on your computer. The browser never shows them in full. They are never written to logs.
