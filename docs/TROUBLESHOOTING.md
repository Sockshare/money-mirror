# Troubleshooting

**First, run the checker.** It finds most problems and tells you the fix:

```bash
source .venv/bin/activate
python scripts/selfcheck.py
```

---

## Starting the app

| What you see | Why | Fix |
|---|---|---|
| `python3: command not found` | Python isn't installed | `sudo apt install python3 python3-venv` |
| `...ensurepip is not available` | Debian/Ubuntu ships Python without venv | `sudo apt install python3-venv` then redo step 2 of the README (or use the no-admin line in the README) |
| `Some required packages are not installed yet` | You skipped `pip install` or forgot to activate the venv | `source .venv/bin/activate` then `pip install -r requirements.txt` |
| `Port 8766 is busy, using 8767 instead` | Something else uses that port | Nothing to fix — use the address the app prints |
| Browser didn't open | Some Linux setups block auto-open | Open a browser yourself and go to `http://127.0.0.1:8766` |
| "The app's server isn't answering. Go back to the terminal…" | The terminal running `python app.py` was closed | Start it again with `python app.py` and reload the page |
| "The app couldn't load its settings" | The settings file is unreadable | Run `python scripts/selfcheck.py`; if needed delete `~/.money_mirror/config.json` |

---

## Importing a file

| What you see | Why | Fix |
|---|---|---|
| "Please upload the CSV file your bank exports… PDF statements won't work." | You picked a PDF, image, or other file | On your bank's site, download **CSV** (sometimes called Excel/Spreadsheet). See the README section *Getting your bank file*. |
| "No table of transactions was found in this file" | The file isn't a real CSV (maybe an HTML page saved as .csv, or a PDF renamed) | Download it again and make sure the format says CSV. Open it in a text editor — you should see commas or semicolons between values. |
| "Couldn't find a date column / an amount column / a description column. Columns found: …" | Your bank uses names the app doesn't know | Open the file in a spreadsheet and rename the headers to `Date`, `Description`, `Amount` (or `Debit` and `Credit`), save as CSV, and import again. Then please open an issue with the original header names so we can add them. |
| "The file had a table, but no rows with a readable date and amount" | Dates or amounts are in a format the app can't parse | Open an issue with 2–3 example rows (change the amounts if you like). |
| "The column names weren't standard, so the app guessed…" | A headerless or oddly labeled file | Check the preview rows. If dates/places/amounts are mixed up, rename the headers as above. |
| "This export lists spending as positive numbers, so the app flipped the signs" | Your bank writes purchases as positive numbers | Usually correct. If income and spending look swapped, open an issue with your bank's name. |
| "Nothing new to add" | Every row was already imported | That's fine — importing the same file twice is safe. |
| "That file is bigger than 30 MB" | A very large export | Export a shorter date range, or split the file. |
| "The file is empty." | The file has zero bytes | Download it again from your bank. |
| Dates are a month off (e.g. 3 April shows as 4 March) | Your bank writes day/month/year and nothing in the file had a day above 12 | Open an issue; as a workaround open in a spreadsheet and save dates as YYYY-MM-DD. |

---

## Numbers look wrong

| What you see | Why | Fix |
|---|---|---|
| A place is in the wrong category | The built-in rules guessed wrong | Transactions tab → change the dropdown. The app remembers it. |
| Spending seems doubled | Credit-card payments from checking were counted as spending | They're in the "Loan & Credit Card Payments" category and excluded from totals automatically. If yours were categorized differently, fix one in Transactions. |
| Transfers to savings show as spending | The transfer wasn't recognized | Change the category to "Transfers" in Transactions. |
| A subscription is missing | It has charged fewer than 3 times, or the amount varied a lot | It will appear after the 3rd charge. Variable bills show with a "varies" tag once they're regular. |
| "Typical month" looks low or high | A partial month, or a one-off big purchase | The current partial month is excluded. Big one-offs are flagged in Alerts; the average still includes them. |
| "This month so far" has no pace | It's the first 10 days of the month | The pace appears from day 10 on. |

---

## Asking questions

| What you see | Why | Fix |
|---|---|---|
| "I couldn't find any … transactions" | The category or place name didn't match, or the dates were wrong | Try the wording from the example chips. Use the merchant name as it appears in Transactions. |
| The answer used the wrong category | The rule-based parser picked a different word | Name the category exactly (e.g. "Coffee & Snacks") or turn on an AI option for better understanding. |
| "Import a bank CSV first" | No data yet | Add a file or load the example data. |
| "Type a question first" | Empty box | Type a question and press Enter. |
| "I didn't understand that one" | The question wasn't about spending/income, or used words the app doesn't know | Use the examples shown, name the category or place as it appears in Transactions, or turn on an AI option. |
| "The AI option isn't working right now (…), so built-in rules were used" | Ollama/cloud is selected but unreachable | Open Settings → Test. The app keeps working with rules meanwhile. |
| Amounts show "$" but my bank uses € or £ | The app doesn't know your currency | Settings → Display → change the symbol. |

---

## The AI (optional)

| What you see | Why | Fix |
|---|---|---|
| "Ollama isn't running (or isn't installed)" | Ollama not installed or not started | Install: `curl -fsSL https://ollama.com/install.sh \| sh` then `ollama pull llama3.2:3b`. If installed, run `ollama serve` in another terminal. |
| "Model '…' is not downloaded" | The model hasn't been pulled | `ollama pull llama3.2:3b` |
| "'…' is not a valid address" | A typo in the Ollama address | Use `http://127.0.0.1:11434` unless you know you changed it |
| "No API key saved. Paste your key in Settings." | Cloud option chosen without a key | Settings → paste the key → Test → Save |
| Test says "ready" but Save says "isn't running" | An environment variable (e.g. `MONEY_MIRROR_PROVIDER`, `OLLAMA_HOST`) is overriding the saved settings | Settings shows a note listing them. Unset them in the terminal and restart the app, or keep using them on purpose. |
| "The API key was rejected" | Typo or expired key | Paste it again in Settings and click **Test** |
| "The AI couldn't place them" | The model didn't recognize the merchants | Set them by hand in Transactions |
| AI answers are slow | Local AI runs on your CPU | Questions take 10–40 s with a 3B model. "No AI" mode is instant for common questions. |

---

## Data

| | |
|---|---|
| Where is my data? | `~/.money_mirror/money.db` (transactions and learned categories) and `~/.money_mirror/config.json` (settings) |
| Delete everything | Settings → **Delete everything**, or delete the folder `~/.money_mirror/` |
| Move the data folder | Start with `MONEY_MIRROR_DATA_DIR=/some/folder python app.py` |

## Still stuck?

1. Run `python app.py --verbose` and look at the messages in the terminal.
2. Open an issue on GitHub and paste the output of `python scripts/selfcheck.py` (it contains no transactions or keys). If the problem is a file that won't import, include the header line and one or two example rows with the amounts changed.
