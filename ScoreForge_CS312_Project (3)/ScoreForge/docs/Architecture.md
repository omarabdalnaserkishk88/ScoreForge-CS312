# Architecture and engineering decisions

## Request lifecycle

Browser GUI → HTTP/JSON request → threaded request handler → authentication and authorization → validation → SQLite transaction → JSON response → GUI update.

The browser only renders data. The server decides identity, role, permitted operations, score range, and room capacity. A caller cannot become an admin by modifying JavaScript or submitting a role field.

## Components

| Component | Responsibility |
|---|---|
| `Server(ThreadingHTTPServer)` | Concurrent HTTP request handling; login-throttling state |
| `Handler` | Exact static file allowlist, JSON endpoints, session/CSRF checks, API errors |
| `Store` | Database initialization, connection management, queries and atomic seat reservation |
| SQLite | Persistent records, foreign keys, uniqueness, score checks and room capacity trigger |
| `static/app.js` | Role-specific navigation, forms, SVG charts, requests, concurrency demo |
| `static/style.css` | Responsive dark interface; local system fonts; no CDN dependencies |

## Synchronization

The critical section contains the entire **check-and-reserve** operation, not just the INSERT.

```python
with self.room_lock, self.transaction() as db:
    # transaction() issues BEGIN IMMEDIATE
    # 1. Validate room and player
    # 2. Return success if this player is already a member
    # 3. Count current occupants
    # 4. Reject if capacity is reached
    # 5. Insert membership and audit entry
    # transaction commits before the lock is released
```

- `threading.Lock` serializes admission threads inside the process.
- `BEGIN IMMEDIATE` obtains SQLite's write reservation before reading capacity. A different process using the same database cannot run a conflicting writer concurrently.
- The `(room_id,user_id)` primary key prevents duplicate membership.
- The capacity trigger rejects an INSERT when the room already has four members.
- The transaction rolls back on failure and the lock is released by its context manager.
- Duplicate join requests are idempotent: all receive success but exactly one membership is added.
- Leaving and resetting also use write transactions. They serialize correctly against admission even though they do not take the application admission lock.
- SQLite serializes writers; WAL permits readers while a writer is active. This is appropriate for the local project scale, not a distributed multiplayer platform.
- Lock acquisition is not a FIFO queue. Threading is concurrent request execution; synchronization controls access to shared state.

## Authentication

Passwords are PBKDF2-HMAC-SHA256 with a random 16-byte salt and 200,000 iterations. Verification uses a constant-time comparison. Session tokens are random; only their SHA-256 hashes are stored. Cookies are HttpOnly and SameSite=Strict. Writes require a per-session CSRF token; provided Origin headers must match the host. Sessions last eight hours. Account disable revokes sessions and seats. Password changes revoke the user's other sessions.

The local HTTP cookie omits Secure because the default classroom endpoint is HTTP loopback. Internet deployment requires HTTPS and a production server configuration. The login limiter permits at most 20 attempts per IP per minute; it is in-memory and intentionally basic.

## Data model

| Table | Key fields | Relationship |
|---|---|---|
| users | id, username, name, role, password, active, demo | Owns scores, memberships, sessions |
| games | id, name, genre, max_score, active | Owns score records |
| scores | id, player_id, game_id, points, note, created_at | Player and game foreign keys |
| rooms | id, name, capacity=4, demo, owner_id | Owns memberships; test rooms owned by admin |
| members | room_id + user_id, joined_at | Unique player membership in a room |
| sessions | hashed token, user_id, csrf, expires | Server-side authentication |
| audit | id, actor_id, action, detail, created_at | Recent administrative and membership events |

Deleting a referenced player/game is restricted. Prefer disabling/archiving when preserving history. Archived game scores remain visible in history and standings. Game maxima cannot be lowered below existing scores. Scores are nonnegative whole numbers. No real student IDs are used as account credentials.

## Frontend state

After a mutation the frontend reloads current server data. Arena status is refreshed explicitly with Refresh; it is not a WebSocket/live-push system. The HTTP explorer records browser-session request metadata without credentials. SVG charts are rebuilt from real per-game results. User-supplied text is escaped before insertion into HTML.


## Reflex Rush game engine

`gameplay.py` adds `play_modes` (difficulty → game) and `rounds` (owner, room, deadline, target token, target coordinates, score counters, status, score reference). Startup is additive and preserves existing records.

Start reserves a main-arena seat and creates a round in the same locked SQLite transaction. An existing round is resumed instead of duplicated. The partial unique index allows only one active round per player.

Each target has an unguessable token, a server issue time and normalized coordinates. Hits/misses reference that token. A consumed token cannot score again; events below 80 ms are rejected. The server computes points and combo bonuses. Expired targets reset combos. The browser renders a responsive canvas and reports interactions, but never sends an authoritative score.

`Server.service_actions()` sweeps expired rounds each server poll (~0.5 s). Saving the score, marking the round finished and releasing membership occur in one transaction. State endpoints also sweep. This makes finalization idempotent and allows recovery after restart. Cancellation, room reset, player disable, and explicit arena leave cancel active rounds without scores.

Difficulty settings: Easy 76 px / 2.5 s; Normal 58 px / 1.6 s; Hard 42 px / 1.0 s. All rounds last 30 seconds. Each hit scores 100 + min(100, 10 × previous consecutive hits). Separate game IDs isolate difficulty leaderboards. Reflex Rush games reject manual POST score creation, although administrators may still correct/delete existing results. A result screen reflects the originally earned round points.

The shared four-seat room may include manually reserved seats as well as active rounds. A fifth applicant receives 409 and retries; no FIFO waiting queue is implemented. Participants play independent boards, not a synchronized shared multiplayer board.

This is not comprehensive anti-cheat: a scripted client could automate otherwise valid challenges. Round timers persist as server wall-clock timestamps. The measured response time includes network latency.
