# Recording Automation (Trimmed Scope)

Scope confirmed with manager: only two things are automated here.

1. **Auto-record start** — NOT code. This is a Google Workspace setting
   (Admin console → Meet video settings → "Meetings are recorded by
   default"), already configured. Google starts recording the moment the
   meeting begins.
2. **Save the recording into the right batch folder** — this code.

Students are already added as calendar guests by your team, and admission
is already handled — no student list, no reminder emails, and no
admission logic are part of this build.

## What the code actually does

1. Reads a small batch list (name, subject, permanent Meet link) from Excel.
2. Reads the calendar to know when each batch's classes happen.
3. After each class ends (+ a grace period), closes the Meet room via the
   Meet API — this is what stops the recording. Easy, few lines, included.
4. Finds the finished recording and moves it into:
   `/Recordings/{Batch Name}/{YYYY-MM-DD} - {Subject}.mp4`
5. Retries checking for the recording a few times (it takes a while to
   process) and alerts by email if it never shows up.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ALERT_EMAIL_TO at minimum
```

Place `client_secret.json` at `credentials/client_secret.json` (see the
original project's Google Cloud setup steps — unchanged: enable Calendar,
Meet, Drive, and Gmail [for alerts] APIs, create a Desktop-app OAuth
Client ID).

## Adding batches

Excel file, one row per batch, columns: **Batch Name, Subject, Meet Link**.

```bash
python -m scripts.add_batch path/to/batches.xlsx
```

## Running

```bash
python -m src.main
```

First run opens a browser for a one-time login. After that it's silent.
Runs continuously — same local-machine caveats as before (must stay on,
awake, connected during class hours). See the original project's README
for OS-specific auto-start instructions (Task Scheduler / launchd /
systemd) — that guidance is unchanged.

## What was intentionally removed from the original build

- Student list / Excel student columns — not needed, students are already
  calendar guests.
- Meet space member sync — not needed, no student list to sync.
- Reminder emails + delivery logging — out of scope.
- Host controls (Restricted access / attendance tracking) auto-check —
  out of scope; admission is already handled by your existing setup.
- `manage_student.py` — not needed.

## Known limitations (same as before, still apply)

- Local-machine dependent — must be running and connected during class hours.
- Recording processing takes time; the retry logic accounts for this but
  will alert if a recording never appears after the configured retries.
- A few Meet API v2 calls are marked `NOTE:` in the code — worth a quick
  check against current Google docs once real credentials are in hand.
