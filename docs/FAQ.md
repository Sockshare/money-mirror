# FAQ

**Is this free?**
Yes. Open source (MIT). No account, no subscription.

**Does it connect to my bank?**
No, never. You download a CSV from your bank's website yourself and drop it in. The app has no idea what your bank login is.

**Is it private?**
Yes. Your file and your numbers stay on your computer. See [PRIVACY.md](PRIVACY.md).

**Do I need AI?**
No. Everything works with built-in rules. AI only helps name unusual merchants and understand tricky questions, and it never sees your amounts or dates.

**Which banks work?**
Almost any. The app detects the column layout on its own — single Amount column or separate Debit/Credit, dates in any common format, semicolons or commas, European decimals, extra header lines. If yours doesn't, [Troubleshooting](TROUBLESHOOTING.md) shows a 1-minute fix, and we'd love an issue with the header names.

**Can I add more than one account?**
Yes. Add checking and every credit card. Re-adding the same file is safe — nothing is counted twice.

**How does it know what's a subscription?**
The same place charging a similar amount on a regular rhythm — monthly, weekly, every 2 weeks, quarterly, or yearly. It needs at least 3 charges (or 2 a year apart).

**Why doesn't my total match my bank statement?**
Money Mirror reports *spending*. It leaves out transfers between your own accounts and credit-card payments so money isn't counted twice (the card charges are already counted). Income is shown separately.

**It put something in the wrong category.**
Transactions tab → change the dropdown. It fixes every transaction from that place and remembers it for next time.

**Can I get my data out?**
Transactions tab → **Export CSV** gives you everything with cleaned names and categories.

**Does it work on Windows or Mac?**
It's built and tested on Linux. It should run on macOS and Windows with the same three commands (use `.venv\Scripts\activate` on Windows), but those aren't tested.

**Where is my data stored?**
`~/.money_mirror/`. Delete the folder to remove everything.

**How do I update the app?**
`git pull` in the project folder, then `pip install -r requirements.txt`.

**Can I run it on a different port, or without opening the browser?**
`python app.py --port 9000` and `python app.py --no-browser`.

**I'm a developer — how is it built?**
See [ARCHITECTURE.md](ARCHITECTURE.md) and run `pytest`.
