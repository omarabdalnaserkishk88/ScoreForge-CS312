# Verification report

## Native desktop update — 12 November 2026

- Re-ran all 22 Python tests: passed.
- `python tools/check_desktop_backend.py`: passed. Two independently launched HTTP backend processes selected distinct ports and shared one temporary SQLite database. Seven concurrent applicants across both processes produced exactly three admissions and four HTTP 409 responses with one pre-existing occupant. Both servers reported four seats occupied. Native-launcher gameplay start/cancel requests also passed.
- `python tools/verify_desktop.py`: passed structural checks for the three form/designer pairs, control declarations, project XML, balanced delimiters and async HTTP/lab wiring. This is **not C# compilation**.
- C# build, Visual Studio Designer rendering, native Windows layout/gameplay, batch launchers and Windows parent-process cleanup remain unverified in this Linux environment without a .NET SDK. See `desktop/README.md` for the Windows acceptance steps.

Date: 10 November 2026. Runtime: Python 3.12.14 on Linux.

## Executed and passed

`python -m unittest discover -s tests -v` — **22 tests passed** (20 HTTP integration tests + 2 launcher regression tests).

| Test | Verified behavior |
|---|---|
| Anonymous/role permissions | 401 without session; 403 for unauthorized admin/player functions |
| CSRF and origin | Missing CSRF token and foreign origin rejected |
| Player API / privacy | GET player works; no password hashes returned; player score history is scoped |
| CRUD / validation / persistence | Player/game/score create/update/delete; bounds; duplicate protection; reopened database retains data; CSV formula guard |
| Three simultaneous applicants | With one inside, all three admitted; final count four |
| Seven simultaneous applicants × 10 | Exactly three admitted and four rejected in every run |
| Duplicate concurrent joins | Eight repeated requests create exactly one membership |
| Live arena lifecycle | Join, repeated join, leave and admin reset |
| Ranking ties | Equal best scores produce ranks 1, 1, 3, 4 |
| Account disable | Session revoked and seat released |
| Database trigger | Direct attempted fifth INSERT rejected |
| Password/logout | Old password invalid, other sessions revoked, logout revokes current session |
| HTTP/static inputs | Invalid payload/ID rejected; arbitrary static paths unavailable |

Also executed: Python compilation and JavaScript syntax check (`node --check static/app.js`).

## Browser validation attempted but blocked

The optional Playwright script was prepared and attempted. The installed Playwright browser bundle was missing. A system Chromium binary existed, but launch failed because this execution environment disallowed its Unix-domain socket operation. The shared browser also could not reach the local server. No successful GUI test or visual rendering claim is made.

Windows batch files are supplied, but were not run on Windows in this environment.

## Manual acceptance checklist on the presentation PC

- [ ] Extract the entire ZIP, launch START_HERE.bat, confirm browser opens.
- [ ] Admin login opens `/admin`; player login in a private window opens `/player`.
- [ ] Check desktop and narrow-screen layout, readable charts and no clipped dialogs.
- [ ] Create/edit/disable a player; confirm disabled account cannot log in.
- [ ] Create/edit/archive a game; reject score beyond its maximum.
- [ ] Create/edit/delete a score; confirm history, standings and charts update.
- [ ] Export CSV and open in a spreadsheet.
- [ ] HTTP explorer returns 200 for an existing player and 404 for a missing player.
- [ ] Concurrency lab: three applicants pass; seven applicants produce three successes and four conflicts.
- [ ] Live arena join/leave/reset; duplicate join does not add a seat.
- [ ] Restart app and confirm data persists.
- [ ] Run RUN_TESTS.bat and confirm all 22 tests pass.

## Optional automated browser smoke test

`tests/browser_smoke.py` is separate from the standard-library test suite. It needs Playwright and a working Chromium installation. Run it against a **disposable seeded database**, because it creates/deletes a test score and changes live arena membership.

```text
python -m pip install playwright
python -m playwright install chromium
python server.py --db data/browser-test.db --port 8080
```

In another terminal:

```text
python tests/browser_smoke.py
```

The optional script checks role routing, score entry/deletion, the concurrency lab, HTTP explorer, navigation, player join/leave, mobile horizontal overflow, and JavaScript errors. Screenshots are written only to local `qa-output/`. It has not successfully completed in the authoring environment.


## Reflex Rush update — seven additional integration tests passed

- Scoring, combo bonuses, miss reset, automatic completion and exactly-once score saving.
- Target replay rejection, owner checks, minimum action interval and role restrictions.
- Five concurrent round starts: four admitted, fifth rejected; after expiry the fifth can retry.
- Refresh/resume, repeated start, cancel, arena leave and admin reset.
- Target expiry and distinct difficulty game IDs.
- Reopening the database preserves records and expired rounds finalize after restart.
- Archived difficulty rejection, manual Reflex score rejection, disabled account cancellation.

Gameplay tests advance an injected server clock instead of sleeping for 30 seconds. HTTP calls, database writes, authentication, locks and transactions remain real. The optional browser smoke script now includes a real 30-second round; browser execution remains blocked by the environment's Unix socket restriction. Python and JavaScript syntax checks pass.

Additional manual checks: play all three difficulties, test touch/mouse target positions, enable sound, reload mid-round, close a tab and confirm automatic save, and run five distinct player sessions in separate browser contexts. Verify the Windows launcher chooses another port when its first choice is unavailable.

Two launcher regression tests also pass: unavailable/forbidden preferred ports fall back to an OS-selected port and the browser opens the actual bound URL; total bind failure does not launch a broken browser page. Windows itself was not available for execution.
