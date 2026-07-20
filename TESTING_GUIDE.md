# Safe Testing Guide — Recording Automation

**Read this before running anything.** The goal is to prove the system works
without touching a single real class, real student, or real recording.

---

## The one rule that matters most

**Never point this system at a permanent Meet link that any real batch
actually uses.** Everything else in this guide exists to protect that rule.

---

## Step 1 — Create a throwaway test batch (do this FIRST, before installing anything)

1. In the test Workspace, create **one brand-new Google Calendar event** —
   not tied to any real class — with a **new** Google Meet link attached
   (click "Add Google Meet video conferencing" when creating the event).
   This generates a new permanent link nobody else uses.
2. Name it something unmistakable, e.g. **"ZZZ-TEST-DO-NOT-USE-FOR-REAL-CLASSES"**.
3. In that event's Meet settings, turn on: Restricted access, "hosts must
   join first," and auto-recording — same as a real batch, so the test is
   realistic.
4. Write down the Meet link — you'll need it in Step 3.

## Step 2 — Set up the project

```bash
unzip class-automation-v2-final.zip
cd class-automation-v2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
mkdir credentials
# place client_secret.json here
cp .env.example .env
```

Edit `.env` — these lines matter for safety:

```
DATABASE_PATH=data/test_class_automation.db
ALERT_EMAIL_TO=your_own_test_email@example.com
TEST_MODE=true
SESSION_END_GRACE_MINUTES=1
RECORDING_CHECK_DELAY_MINUTES=2
```

`TEST_MODE=true` and a `test_` database filename are your safety net — as
long as you never import a real batch list into this database, nothing
real can be touched, because the system only ever acts on batches it
finds in its own database.

## Step 3 — Import ONLY the test batch

Create `test_batch.xlsx` with exactly one row:

| Batch Name | Subject | Meet Link |
|---|---|---|
| ZZZ-TEST-DO-NOT-USE-FOR-REAL-CLASSES | Test | *(the link from Step 1)* |

```bash
python -m scripts.add_batch test_batch.xlsx
```

**Do not import any real Excel sheet at this stage.** The database should
contain exactly one batch — the test one.

## Step 4 — Run it

```bash
python -m src.main
```

Browser opens — log in with a **test Workspace account** (not a real
teacher's account). Leave the terminal running.

## Step 5 — Trigger a real end-to-end test

- Join the test Meet link, let it run a minute or two, then leave so the
  conference actually ends.
- Watch the terminal / `logs/system.log`. Within a few minutes you should see:
  - `Closed Meet session for batch 'ZZZ-TEST-DO-NOT-USE-FOR-REAL-CLASSES'.`
  - `Filed recording for batch '...' -> https://drive.google.com/...`

## Step 6 — Verify nothing else was touched

- Check Google Drive: a new `Recordings/ZZZ-TEST-DO-NOT-USE-FOR-REAL-CLASSES/`
  folder should exist, containing only the one test recording.
- Check the real class calendars/Drive folders — confirm nothing there changed.
- Check `logs/system.log` — every line should only ever mention the test batch name.

## Step 7 — Before going anywhere near real classes

- Stop the script (Ctrl+C).
- Delete the test database: `rm data/test_class_automation.db`
- Delete the test Drive folder if you want a clean slate.
- Only after this test fully passes, repeat with the **real** batch list —
  and even then, start with `TEST_MODE=false` on just **one real batch**
  for one class before rolling out to all of them.

---

## Red flags — stop immediately if you see any of these

- The system logs mention a batch name you don't recognize as your test batch.
- A recording appears in a real batch's Drive folder during this test.
- `endActiveConference` is called on a space you didn't create for testing.

If any of these happen, stop the script, and check `DATABASE_PATH` in
`.env` — it likely points at a database that already has real batches in
it from a previous run.
