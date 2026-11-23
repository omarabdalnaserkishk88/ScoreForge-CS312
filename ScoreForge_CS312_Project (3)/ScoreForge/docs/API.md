# HTTP API reference

Base: `http://127.0.0.1:8080`. Requests and responses use JSON except the CSV export. Error responses use `{"error":"message"}`. IDs are numeric database IDs, not university IDs.

Login returns a cookie and a CSRF token. Send the cookie for authenticated requests and `X-CSRF-Token` for POST/PUT/DELETE. Use `Content-Type: application/json` for request bodies. Requests larger than 16 KiB are rejected. This API intentionally does not allow cross-origin browser access.

| Method | Path | Access | Purpose/body |
|---|---|---|---|
| POST | /api/login | Public | `{"username":"admin","password":"Admin@12345"}` |
| GET | /api/me | Signed in | Current user and session CSRF token |
| POST | /api/logout | Signed in | `{}`; revoke this session |
| POST | /api/password | Signed in | `{"current":"...","password":"..."}` |
| GET | /api/players | Signed in | Player list; no password data |
| GET | /api/players/2 | Signed in | One player by ID |
| POST | /api/players | Admin | `{"name":"Ali","username":"ali","password":"Player@12345"}` |
| PUT | /api/players/2 | Admin | `{"name":"Mohamed Moustafa","active":1}` |
| DELETE | /api/players/2 | Admin | Delete only when unreferenced |
| GET | /api/games | Signed in | Game catalog |
| POST | /api/games | Admin | `{"name":"Game","genre":"Arcade","max_score":1000,"active":1}` |
| PUT | /api/games/1 | Admin | Same fields; edit existing game |
| DELETE | /api/games/1 | Admin | Delete only when unreferenced |
| GET | /api/scores | Signed in | Admin: all scores; player: own scores only |
| POST | /api/scores | Admin | `{"player_id":2,"game_id":1,"points":9000,"note":"Final"}` |
| PUT | /api/scores/1 | Admin | Same fields; edit score |
| DELETE | /api/scores/1 | Admin | Delete score |
| GET | /api/leaderboard | Signed in | Best score, average, plays and rank per game/player |
| GET | /api/rooms | Signed in | Live arena occupancy and members |
| POST | /api/rooms/join | Player | `{"room_id":1}`; identity comes from session |
| POST | /api/rooms/leave | Player | `{"room_id":1}` |
| POST | /api/rooms/reset | Admin | `{"room_id":1}` |
| GET | /api/audit | Admin | Latest 100 events |
| GET | /api/export | Admin | CSV score export |
| POST | /api/demo/start | Admin | `{}`; reset this admin's separate test room; seed one occupant |
| POST | /api/demo/join | Admin | `{"room_id":2,"player_id":7}`; use IDs returned by demo start |
| GET | /api/demo/state | Admin | This admin's test room occupancy |

## Example player response

```json
{"player":{"id":2,"name":"Mohamed Moustafa","active":1}}
```

## Status codes

- `200`: read/update/delete success, including idempotent re-join.
- `201`: record or test arena created.
- `400`: invalid JSON/field, invalid player/game, or out-of-range score.
- `401`: no valid session or invalid credentials.
- `403`: role, CSRF or cross-origin check failed.
- `404`: resource or route not found.
- `409`: arena full, duplicate record, or foreign-key conflict.
- `413`: request too large; `415`: unsupported request content type.
- `429`: login throttled; `503`: database busy/unavailable.

## Browser demonstration

Log in, open **HTTP explorer**, select **GET /api/players**, then **Send request**. The response comes from SQLite via an actual network request. Browser developer tools → Network can independently show the method, endpoint, status, and response.

The admin-only demo endpoint accepts synthetic test-player IDs solely for the separate demo room. The live join endpoint never accepts another player's identity from the client.


## Gameplay endpoints

The normal cookie and CSRF rules apply. Client-supplied score fields are ignored.

| Method | Path | Role | Body / result |
|---|---|---|---|
| GET | /api/play/state | Player | Latest round and difficulty definitions; resumes active round |
| POST | /api/play/start | Player | `{"mode":"normal"}`; reserves seat or returns existing round |
| POST | /api/play/hit | Player | `{"round_id":"…","target_id":"…"}`; server computes points |
| POST | /api/play/miss | Player | Same IDs; resets combo, issues next target |
| POST | /api/play/cancel | Player | `{}`; cancel active round and release seat |
| GET | /api/play/sessions | Admin | Latest 100 round sessions |

Round responses contain `status`, `remaining`, `points`, `hits`, `misses`, `combo`, `best_combo`, `average_ms`, `accuracy`, and `score_id`. Active rounds include the current target ID, normalized x/y coordinates, size, and remaining target lifetime. Finished rounds have a saved score ID, unless that score was subsequently deleted by an administrator.

409 indicates a full arena, archived difficulty, or stale target; 429 indicates an impossibly rapid event under the minimum interval. A repeated start resumes the same round. Completion is automatic on the server, not a client-submitted final-score request.

With START_HERE.bat the base URL is usually port 5050; use the actual printed URL. Direct `python server.py` retains default port 8080 unless `--port` is supplied.
