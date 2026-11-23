# ScoreForge · CS312

**New native desktop option:** open `ScoreForge.Desktop.sln` in Visual Studio (purple). It includes editable WinForms Designer files and connects to this current Python/SQLite backend with login, gameplay, HTTP and synchronization. Read `VISUAL_STUDIO_NEW_VERSION_AR.md` or `desktop/README.md`. `START_HERE.bat` below still opens the original browser version.

**Simple Game Score Management System — Project 97**  
Misr University for Science & Technology · Modern Development Tools

A local web application with a playable 30-second reaction game, a dark dashboard, separate administrator and player workspaces, real HTTP/JSON requests, SQLite persistence, score charts, and a thread-safe four-player arena.

## Start on Windows

1. Extract the **whole ZIP** into a normal folder. Do not run from inside the archive.
2. Install **Python 3.10 or newer** if it is not already installed; enable “Add Python to PATH”.
3. Open `ScoreForge`, then double-click **START_HERE.bat**.
4. The browser opens at the local address printed in the terminal (usually `http://127.0.0.1:5050`). Keep the terminal window open.
5. Sign in using a demo account below. Account roles determine the destination automatically.

No pip packages, npm packages, SQL Server, internet connection, or build step are needed to run the application once Python is installed. This is source code, not a compiled Windows EXE.

| Role | Username | Initial password | Workspace |
|---|---|---|---|
| Admin | `admin` | `Admin@12345` | `/admin` |
| Player | `player1` | `Player@12345` | `/player` |
| Other demo players | `player2`, `player3`, `player4` | `Player@12345` | `/player` |

These are intentionally visible classroom demo credentials. Use **Account** to change a password. Data is seeded only when the database is first created. An environment variable, `SCOREFORGE_ADMIN_PASSWORD`, can override the administrator's initial password. It does not reset an existing password.

### Terminal launch

```text
python start.py
```

On Linux/macOS, use `python3 start.py` or `./start.sh`. To choose a different port:

```text
python server.py --port 8081
```

For an empty workspace with only the administrator, use a **new database path**:

```text
python server.py --db data/empty.db --no-demo
```

The concurrency lab requires the seeded test accounts, so it is unavailable in a database created with `--no-demo`.

## Play Reflex Rush

Sign in as **player1 / Player@12345**. The **Play Reflex Rush** page opens automatically. Choose Easy, Normal, or Hard and press **Start round**. Tap/click the glowing target for 30 seconds. Results save automatically, and the game-specific leaderboard and charts update.

- Hit: 100 points + 10 for each earlier hit in the current streak, capped at +100 bonus.
- Missing or letting a target fade breaks the streak.
- Easy / Normal / Hard have different target sizes and lifetimes, and separate rankings.
- Four shared arena seats maximum. A fifth player receives a full-arena message and can retry when a seat is free; there is no automatic FIFO queue.
- The server owns round time, accepted events and scoring. The client never submits a final score.
- At 30 seconds the result saves once and the seat is released, even if the tab has closed. If the server itself stops, it finalizes expired rounds after restart.
- Stop round cancels without saving. Refreshing resumes an active round. Switching tabs does not pause the clock.
- Admin → Play Reflex Rush shows a session monitor; administrators do not occupy player seats.

## Upgrade from the previous ZIP

Stop the old server first. Extract this version into a **new folder**. To keep existing accounts/results, copy the old `data/scoreforge.db` into the new `ScoreForge/data/` folder before starting (back up the old file first). New gameplay tables and three difficulty-specific game records are added automatically. Do not copy a database while a server is writing to it.

The launcher now tries port 5050, 8081, 8765, then an automatically assigned free port. Always use the address it opens/prints; do not keep an old bookmark to port 8080.

## What is implemented

- **Authentication:** salted PBKDF2 password hashes, server-side sessions, HttpOnly / SameSite cookies, CSRF checks, login throttling, password change, and logout.
- **Roles:** players access their own score history, public standings, game catalog and live arena. Administrators manage accounts, games and scores, export CSV, reset the arena, and inspect activity.
- **Player management:** create, rename, disable/reactivate, and delete unreferenced player records. Disabling revokes sessions and releases seats.
- **Games:** create, edit, archive, and delete unreferenced games, with per-game scoring limits.
- **Scores:** create, edit, delete, search/filter by game, and export CSV with spreadsheet-formula protection.
- **Graphics:** SVG bar charts derived from database results, per-game best scores, averages, and player counts.
- **Leaderboards:** each player's best score per game; ties share competition ranks, e.g. `1, 1, 3`.
- **HTTP explorer:** send actual `GET /api/players`, `GET /api/players/{id}`, and other API requests, inspect status/latency/JSON, and see recent browser request activity.
- **Threading + synchronization:** a threaded server with a lock and SQLite transaction around admission; the main arena holds at most four players.
- **Concurrency lab:** starts a separate test arena with one occupant; sends either three or seven parallel requests and verifies stored occupancy. It never resets the live arena.
- **Persistence:** SQLite constraints, foreign keys, parameterized SQL, audit history, and a database capacity trigger.

## The three additional requirements

| Requirement | Demonstration | Code |
|---|---|---|
| Admin/player login and dedicated pages | Login as `admin`, then in a private browser window as `player1` | `server.py`: `Handler.auth`, login route; `static/app.js`: `renderLogin`, `shell` |
| HTTP request returning player/system data | HTTP explorer → send request → inspect real JSON and HTTP 200 | `Handler.route`; frontend `api()` uses `fetch()` |
| Synchronization with maximum four players | Concurrency lab → 3 applicants, then 7 applicants | `Store.reserve`, `ThreadingHTTPServer`, SQLite trigger; `renderLab` uses `Promise.all` |

“Synchronization” protects shared state from a race condition. It does **not** guarantee FIFO arrival order. The accepted applicants may differ between runs; the maximum occupancy must not.

## Project layout

```text
ScoreForge/
  START_HERE.bat          Windows launcher
  RUN_TESTS.bat           Windows integration-test launcher
  start.py / start.sh     Cross-platform startup
  server.py              Threaded HTTP server, authentication, services, SQL schema
  gameplay.py            Round state, timed challenges, authoritative score calculation
  static/                HTML, CSS, JavaScript, local SVG favicon
  data/                  SQLite database created on first run
  tests/test_system.py   13 core integration tests using real local HTTP connections
  tests/test_gameplay.py  7 gameplay integration tests using a controlled clock
  tests/test_launcher.py  2 launcher fallback regression tests
  tests/browser_smoke.py Optional browser test (separate Playwright dependency)
  docs/                  Architecture, API, requirements, demo script, Arabic guide
```

## Tests

```text
python -m unittest discover -s tests -v
```

All standard-library integration tests run against a **temporary database**. They do not modify your application data.

**Verified in the authoring environment:** all 20 integration tests and 2 launcher regression tests pass; Python and JavaScript syntax checks pass. Includes ten repeated seven-applicant races, idempotent duplicate joins, role checks, database persistence, and direct database capacity enforcement.

**Not verified here:** visual/browser interaction and Windows launcher execution. Browser checks were attempted but blocked by execution-environment socket restrictions and local browser connectivity. `docs/TestingReport.md` distinguishes verified and outstanding checks. Run the included acceptance checklist on Windows before presenting.

## Scope and choices

This version replaces the earlier C# WinForms + SQL Server source with **Python + SQLite + a browser GUI**, allowing the requested HTTP and multithreading demonstrations without third-party runtime dependencies. The supplied project row specifies GUI, graphics, and database integration, but does not specify a programming language. If your instructor separately requires C# / WinForms / SQL Server, that additional constraint must be checked before submitting this version.

This is a score management system **with one playable game: Reflex Rush**. The other catalog games are score-management examples, not playable game implementations. Players play independent rounds against a shared leaderboard, not a real-time shared board. All rounds use the existing main four-seat arena. A manually reserved seat stays until Leave/Reset/disable; a game round's seat releases automatically on completion or cancellation.

The challenge tokens, deadline checks and minimum action interval reject simple replay and arbitrary client-submitted scores. They are not a complete anti-bot system: a custom client could automate valid target events. Server receipt time includes local HTTP latency; the displayed response average is not a clinical reaction-time measurement.

The server binds to loopback by default and is intended for a local classroom demo. It is not an internet production deployment. HTTPS termination, production hosting, recovery flows, pagination and monitoring are outside this version's scope. Sessions expire after eight hours. Demo races share one demo arena per administrator; avoid running two race demonstrations simultaneously from the same admin account.

Read **docs/START_HERE_AR.md** for Egyptian Arabic instructions and **docs/DemoScript.md** for the presentation walkthrough.
