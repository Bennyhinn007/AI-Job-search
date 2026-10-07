# AI Job Search 🚀

A lightweight, personal **job-discovery and resume-matching automation** tool.

It automatically discovers recently posted IT/engineering jobs from public job
APIs, filters and deduplicates them, compares each job description against your
resume, ranks the best opportunities, and emails you a clean digest — so you
stop manually scrolling job boards every day.

> This is **not** an auto-apply bot. It discovers, ranks, and notifies. **You**
> decide where to apply.

---

## 1. What the project does

```
Job Sources (Adzuna + Remotive)
      ↓ normalize
Normalized Job objects
      ↓ filter (role + posting age)
Relevant, recent jobs
      ↓ deduplicate (SQLite)
New jobs only
      ↓ load resume (PDF/TXT)
      ↓ resume ↔ JD matching (keyword, or LLM if configured)
      ↓ rank (match score + recency + location)
Top opportunities
      ↓ render + send email digest
      ↓ store processed jobs (so they are never re-sent)
```

## 2. Features

- **Source-agnostic architecture** — add new job boards by implementing one
  `JobSource` subclass. Ships with **Adzuna** (keyed) and **Remotive** (keyless).
- **Broad IT/engineering role coverage** — software, backend, frontend, full-stack,
  DevOps, cloud, security, AI/ML, data, QA, systems, networking, and more.
- **Recency windows** — default 24 hours, `--days 7` for a weekly sweep.
- **SQLite deduplication** — the same job is never emailed twice. Jobs are marked
  seen **only after a successful email**, so a failed send is retried next run.
- **Multi-resume matching** — drop several resumes (one per career track) into
  `resume/`; each job is scored against all of them and the **best-fit** profile
  wins, shown in the digest.
- **Resume matching, two modes**:
  - **Keyword** (default, offline, zero cost) — skill overlap scoring.
  - **LLM** (optional) — richer matching when `GOOGLE_API_KEY` (Gemini) or
    `OPENAI_API_KEY` is set, with **automatic fallback to keyword** on any failure.
- **Smart ranking** — match score first, with recency, Indian-city priority, and
  remote as secondary boosts. Location never overpowers a clearly better match.
- **Clean email digest** — HTML + plain-text, with per-job match %, matching and
  missing skills, and an APPLY / CONSIDER / LOW PRIORITY recommendation.
- **Dry-run mode** — preview the full digest in your terminal with **no email and
  no credentials required**.
- **Graceful degradation** — one failing source, one bad job, or an unavailable
  LLM never crashes the run.

## 3. Architecture

```
AI-Job-search/
├── main.py             # CLI + pipeline orchestration
├── config.py           # all settings + skills vocabulary + target roles
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── database/           # jobs.db created here at runtime
├── resume/             # put resume.pdf or resume.txt here
│   └── resume.sample.txt   # sample resume for a keyless demo
├── src/
│   ├── models.py       # Job dataclass + normalization
│   ├── job_fetcher.py  # JobSource interface + AdzunaSource + RemotiveSource
│   ├── filters.py      # relevance + recency filtering
│   ├── database.py     # SQLite dedup (parameterized queries)
│   ├── resume_parser.py# PDF/TXT loading + skill extraction
│   ├── matcher.py      # keyword + optional LLM matching
│   ├── ranking.py      # rank scoring
│   └── email_sender.py # HTML + text digest, Gmail SMTP
└── tests/
    ├── test_pipeline.py
    └── test_dry_run.py
```

## 4. Installation

Requires **Python 3.10+**.

```bash
git clone https://github.com/Bennyhinn007/AI-Job-search.git
cd AI-Job-search
```

## 5. Virtual environment setup

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux/macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 6. Installing dependencies

```bash
pip install -r requirements.txt
```

(Optional, only for LLM matching: `pip install openai`.)

## 7. Adzuna API setup

Adzuna is the primary source and is **optional** — without it the app still runs
on the keyless Remotive source.

1. Register (free) at <https://developer.adzuna.com/>.
2. Create an app to get your **App ID** and **App Key**.
3. Put them in `.env` as `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.

The country defaults to India (`ADZUNA_COUNTRY=in`).

## 8. Gmail App Password setup

Needed only to actually send email (not for `--dry-run`).

1. Enable **2-Step Verification** on your Google account.
2. Go to <https://myaccount.google.com/apppasswords>.
3. Generate a 16-character **App Password**.
4. Put it in `.env` as `EMAIL_PASSWORD` (your Gmail address goes in
   `EMAIL_ADDRESS`, the destination in `RECIPIENT_EMAIL`).

> Use the App Password, **never** your normal Google password.

## 9. Optional LLM API setup (Gemini or OpenAI)

LLM matching is optional. Keyword matching works with no key. If a key is
present the app uses the LLM and **silently falls back** to keyword matching on
any error. Provider preference: **Gemini first, then OpenAI**.

**Option A — Google Gemini (has a free tier):**
1. Create a key at <https://aistudio.google.com/app/apikey>.
2. Install the SDK: `pip install google-generativeai`.
3. Set `GOOGLE_API_KEY` in `.env` (and optionally `GEMINI_MODEL`,
   default `gemini-1.5-flash`).

**Option B — OpenAI (paid):**
1. Get a key from <https://platform.openai.com/api-keys>.
2. Install the SDK: `pip install openai`.
3. Set `OPENAI_API_KEY` in `.env` (and optionally `OPENAI_MODEL`).

If both keys are set, Gemini is used first.

## 10. Resume placement (multi-resume)

Drop **one or more** resumes into the **`resume/`** folder as `.pdf` or `.txt`.
Every file there (except `resume.sample.txt` and `.gitkeep`) is loaded as a
separate **profile**. Each job is matched against **every** profile and the
**best-fitting** one wins — the digest shows which profile matched (e.g.
*Best-fit resume: Cybersecurity*).

Name files with an optional ordering prefix; the label is derived from the name:

```
resume/
├── 01-cybersecurity.txt        → "Cybersecurity"
├── 02-data-analytics.txt       → "Data Analytics"
├── 03-mern-fullstack.txt       → "Mern Fullstack"
├── 04-software-developer.txt   → "Software Developer"
└── 05-fullstack-cybersecurity.txt → "Fullstack Cybersecurity"
```

A single resume works too — it's just one profile. To try the tool immediately
without your own resume, copy the included sample:

```bash
# Windows
Copy-Item resume\resume.sample.txt resume\resume.txt
# Linux/macOS
cp resume/resume.sample.txt resume/resume.txt
```

Resume files are gitignored and never committed.

## 11. .env configuration

```bash
# Windows
Copy-Item .env.example .env
# Linux/macOS
cp .env.example .env
```

Then edit `.env`. Minimum to send real email: `EMAIL_ADDRESS`, `EMAIL_PASSWORD`,
`RECIPIENT_EMAIL`. Everything else has sensible defaults.

| Variable | Purpose |
|---|---|
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Adzuna credentials (optional) |
| `ADZUNA_COUNTRY` | Adzuna country code (default `in`) |
| `EMAIL_ADDRESS` / `EMAIL_PASSWORD` | Gmail sender + App Password |
| `RECIPIENT_EMAIL` | Where the digest is sent |
| `GOOGLE_API_KEY` / `GEMINI_MODEL` | Optional Gemini LLM matching (preferred) |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Optional OpenAI LLM matching |
| `MAX_JOB_AGE_DAYS` | Default posting window (default 1) |
| `MIN_MATCH_SCORE` | Minimum score to include (default 60) |
| `MAX_EMAIL_JOBS` | Max jobs per digest (default 10) |
| `APPLY_THRESHOLD` / `CONSIDER_THRESHOLD` | Recommendation cutoffs (80 / 60) |
| `LOCATION_PRIORITY` | Comma-separated ranking boost order |

## 12. Running the application

```bash
python main.py
```

Full run: fetch → filter → dedup → match → rank → **send email** → store seen.

## 13. Dry-run mode

Preview everything in your terminal, no email, no credentials needed:

```bash
python main.py --dry-run
```

Zero-setup demo (keyless Remotive + sample resume + 7-day window):

```bash
# after copying the sample resume (step 10)
python main.py --dry-run --days 7 --min-score 0
```

### All CLI options

```bash
python main.py                 # full run with defaults
python main.py --dry-run       # preview only, never send
python main.py --days 1        # last 24 hours (default)
python main.py --days 7        # last 7 days
python main.py --limit 10      # cap jobs in the digest
python main.py --min-score 60  # only include match score >= 60
python main.py --fetch-only    # fetch + filter + dedup, then stop
python main.py --check         # print a secret-safe config summary
```

Flags combine, e.g. `python main.py --dry-run --days 7 --min-score 70`.

## 14. Windows Task Scheduler

The repo ships a one-command setup. From the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_schedule.ps1
```

This registers a daily task named **"AI Job Search Daily"** that runs every
morning at 9:00 AM and emails the digest. Pick a different time with:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_schedule.ps1 -Time "08:30"
```

It runs `run_job_radar.bat`, which `cd`s into the project folder (so `.env`,
`resume/`, and `database/` resolve correctly), uses the project `.venv` if
present, and appends output to `logs\job_radar.log`.

Useful commands:

```powershell
schtasks /Run    /TN "AI Job Search Daily"      # run it now to test
schtasks /Query  /TN "AI Job Search Daily"      # see next run time
schtasks /Delete /TN "AI Job Search Daily" /F   # remove the schedule
```

Prefer to do it manually? The underlying command is:

```powershell
schtasks /Create /SC DAILY /ST 09:00 /TN "AI Job Search Daily" ^
  /TR "C:\path\to\AI-Job-search\run_job_radar.bat" /RL LIMITED /F
```

## 15. Linux/macOS cron

Edit your crontab:

```bash
crontab -e
```

Run every morning at 9:00 AM (note the `cd` so relative paths resolve):

```cron
0 9 * * * cd /path/to/AI-Job-search && /path/to/AI-Job-search/.venv/bin/python main.py >> logs/job_radar.log 2>&1
```

Confirm it was added with `crontab -l`.

## 16. Troubleshooting

| Symptom | Fix |
|---|---|
| `No resume found` | Place `resume/resume.pdf` or `resume/resume.txt` (step 10). |
| `Email credentials not configured` | Fill `EMAIL_*` in `.env`, or use `--dry-run`. |
| Login fails when sending | Use a Gmail **App Password**, not your account password. |
| No jobs found | Widen the window: `--days 7`; lower `--min-score`. |
| Adzuna returns nothing | Check `ADZUNA_APP_ID`/`KEY`; the app still uses Remotive without them. |
| LLM errors | They are logged and the app auto-falls back to keyword matching. |
| Emoji looks garbled in the console | Cosmetic only on some Windows shells; the email renders correctly. |

## 17. Future roadmap (not in V1)

- Web dashboard and application tracking
- Multiple resume versions
- Vector/semantic ranking with embeddings
- Telegram / WhatsApp notifications
- More job sources (additional public/permitted APIs)

---

### Security notes

- `.env`, `database/*.db`, and resume files are gitignored and never committed.
- Secrets are never printed; `--check` reports only *set / not set*.
- All SQLite access uses parameterized queries.
- Job-description HTML is stripped and escaped before going into emails; job
  content is never executed.
- The tool does not auto-apply and does not bypass any site's access controls.
