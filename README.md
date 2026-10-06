# Daily Update

A free, automated daily monitoring report: public holdings, portfolio companies, the Megatron portfolio, sponsors, industry themes and a calendar. Published as a website (GitHub Pages) and emailed each morning as a summary with a PDF attached.

- `watchlist.json`: companies, sections and settings (also editable from the site's Watchlist page)
- `pipeline/`: the daily job (prices, news, valuations, AI briefing, rendering, email)
- `templates/`: website, email and PDF layouts
- `docs/`: the published site (generated, plus `assets/`)
- `data/`: memory between runs (valuations, seen headlines, daily snapshots) and `events.json`
- `apps_script/Code.gs`: the passcode-protected backend for Watchlist edits

Start with **SETUP.md**.
