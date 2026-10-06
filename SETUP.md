# Daily Update — setup guide

About 45 minutes, once. Everything here is free. You need: your GitHub account, a Google account (for Gmail, Gemini and Apps Script), and your work Outlook address.

## How it works

Every day at 06:00 Doha time, GitHub runs `pipeline/run.py`. It pulls prices (Yahoo Finance), news and press releases (Google News), and calendar dates (FRED and Yahoo). It updates valuations from funding headlines and asks Gemini to write the briefing. Then it publishes the website from the `docs/` folder and, on send days, emails the summary and a PDF to your work Outlook.

The Watchlist page on the site lets you add, edit and remove companies with a passcode. Each change triggers a refresh within about 3 minutes, without sending an email.

---

## 1. Replace the old project in your repo

1. Open your repo `Project-Megatron---Daily-Update` on GitHub.
2. Delete the old files: `fetch_data.py`, `index.html`, `data.json`, and the old workflow file inside `.github/workflows/` (the one named "Daily briefing update").
3. Upload everything from this folder, keeping the folder structure (Add file → Upload files, then drag the whole folder contents in). Make sure `.github/workflows/daily-update.yml` arrives. Hidden folders are sometimes skipped by drag-and-drop; if it's missing, create it with Add file → Create new file and paste its contents.

## 2. Serve the site from the `docs` folder

Settings → Pages → Build and deployment → Source: **Deploy from a branch** → Branch: **main**, folder: **/docs** → Save.

The address stays `https://sabyasaches.github.io/Project-Megatron---Daily-Update/`. If it ever changes, update `site_url` in `watchlist.json`.

## 3. Sender account (Gmail) and your Outlook address

The email is sent from a Gmail account to your work Outlook. Use a separate Gmail account for this if you prefer.

1. In that Google account, turn on 2-Step Verification (myaccount.google.com → Security).
2. Create an app password: myaccount.google.com/apppasswords → name it "Daily Update" → copy the 16-character password.
3. In GitHub: Settings → Secrets and variables → Actions → New repository secret. Add:
   - `GMAIL_ADDRESS`: the Gmail address
   - `GMAIL_APP_PASSWORD`: the 16-character app password, no spaces
   - `EMAIL_TO`: your work Outlook address

Corporate mail filters sometimes quarantine automated mail from Gmail. After the first send, check Junk and any quarantine notice, add the Gmail address to Safe Senders, and ask IT to allowlist it if needed.

## 4. API keys (free)

Add these as repository secrets too:

- `GEMINI_API_KEY`: from aistudio.google.com → Get API key. Writes the briefing and reads funding headlines. Google may use free-tier inputs to improve its products; the inputs here are public headlines and prices. Without this key the report still works, with an automatic summary instead.
- `FRED_API_KEY`: from fredaccount.stlouisfed.org → API Keys. Adds US data releases (CPI, jobs report, GDP) to the Calendar.

The old `FINNHUB_KEY` secret is no longer used; you can delete it.

## 5. Watchlist backend (Google Apps Script)

1. Create a GitHub token: github.com/settings/personal-access-tokens → Generate new token (fine-grained) → Repository access: **Only select repositories** → this repo → Permissions → **Contents: Read and write** → Generate. Copy it.
2. Go to script.google.com → New project. Replace the code with `apps_script/Code.gs`.
3. Project Settings (gear icon) → Script properties → add:
   - `PASSCODE`: a passcode you'll share with people allowed to edit
   - `GITHUB_TOKEN`: the token from step 1
   - `REPO`: `sabyasaches/Project-Megatron---Daily-Update`
   - `BRANCH`: `main`
4. Deploy → New deployment → type **Web app** → Execute as: **Me** → Who has access: **Anyone** → Deploy. Approve the permissions prompt (Google warns because the script is yours and unverified; choose Advanced → Go to project).
5. Copy the Web app URL. In GitHub, open `watchlist.json` → edit → paste it as the value of `"apps_script_url"` → commit.

"Anyone" only means the page can reach the script. Every change still needs the passcode.

## 6. First run

Actions tab → **Daily Update** → Run workflow → set email to **yes** → Run. It takes about 5 minutes. Then open the site and check your Outlook inbox.

The first run establishes the baseline: "What changed" has nothing to compare against until the second day, and every headline shows as new.

## 7. Check the details only you can confirm

- **Tickers.** On the Markets and Sponsors pages, any company showing "no data" has a wrong ticker. Please verify `BEEMA.QA`, `QATI.QA` and `CBQK.QA` (Qatar Stock Exchange), `CVC.AS` (Euronext Amsterdam) and `BZAI` (Blaize). Fix them on the Watchlist page.
- **Websites.** Press releases are pulled from each company's own site. These have none set yet: Beema, Arini Capital Management, Deutsche ReGas, AIP, Campus AI, Qatar Insurance Company. Add them with Edit on the Watchlist page.
- **Valuations.** OpenAI, Anthropic and Altera carry over the manual figures from the old site, marked "manual entry · unverified". They update automatically when a closed round with a stated valuation appears in the news. To fix a figure yourself, enter it under Valuation override; it is then pinned and never overwritten.
- **Calendar.** Fed meeting dates for late 2026 are in `data/events.json`. Add ECB meetings, 2027 dates, IPO windows and anything else you want to track there.

---

## Everyday settings (all in `watchlist.json` → `settings`)

| Setting | What it does |
|---|---|
| `send_days` | Days the email goes out (default Sun–Thu). The website updates every day. |
| `thresholds` | When a price or volume move gets flagged. |
| `news_window_hours` | How far back news is shown (default 72). |
| `calendar_days` | How far ahead the Calendar looks (default 21). |
| `attach_pdf` | Attach the PDF to the email (true/false). |
| `benchmarks` | Index, rate and commodity tickers shown with the holdings. |
| `gemini_model` | The Gemini model name. If Google retires it, the run log will show an error and the report falls back to the automatic summary; change this to the current free model. |

The send time is in `.github/workflows/daily-update.yml` (`cron: "0 3 * * *"` is 03:00 UTC). GitHub may start scheduled runs 10 to 30 minutes late at busy times.

Industry themes and macro topics are the `industry` and `macro` lists at the bottom of `watchlist.json`. For very large firms marked `"busy": true`, only coverage matching the `busy_focus` words is kept, so routine stories about Goldman Sachs or BlackRock don't flood the Sponsors page.

## Troubleshooting

- **No email:** Actions → latest run → "Build the report" log. "Email skipped" means a secret is missing. An authentication error means the app password is wrong. If the log says it was sent, check Junk and quarantine.
- **Watchlist says "Wrong passcode" or a GitHub error:** check the script properties. A 401/403 from GitHub means the token expired or lacks Contents write access.
- **A company shows irrelevant news:** edit it and add must-match words, like the taxi/rideshare words used for Firefly.
- **Test locally:** `pip install -r requirements.txt`, then `python tests/make_fixture.py` and `python -m pipeline.run --fixture tests/fixture.json --email no --no-ai`, and open `docs/index.html`. The fixture uses synthetic price histories; don't commit the resulting `docs/` and `data/` changes.
