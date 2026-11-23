# ScoreForge Desktop - new-feature client

This is a **native C# Windows Forms client for the current Python backend**, not the old C# / SQL Server application and not an embedded browser wrapper. All current backend features remain in the package. The original browser client is retained too.

## Open / build

Open `../ScoreForge.Desktop.sln` in Visual Studio 2022 17.8+ with **.NET desktop development** and .NET 8 SDK. Install Python 3.10+ on PATH. There are no third-party NuGet packages in the desktop project; .NET/Windows targeting packs must be installed or restored.

Right-click `Forms/LoginForm.cs`, `MainForm.cs`, or `EditorForm.cs` → View Designer (Shift+F7). Expand each `.cs` node for the corresponding `.Designer.cs`. Do not open the designer partial by itself to view the form. `MainForm` uses TabPages selected by a sidebar; use Document Outline to choose pages at design time. Data rows, generated editor fields, GDI+ game targets and chart bars appear at runtime.

F5 launches login and automatically starts a Python loopback backend on an available port. No database, HTTP calls or Python processes run in a form's designer constructor. The code-behind runtime overload wires event handlers and networking. `RUN_DESKTOP.bat` is an optional .NET CLI launcher.

## Feature mapping

| New feature | Native client | Existing server |
|---|---|---|
| Login / roles / password | LoginForm + ApiClient cookie/CSRF session | Handler.auth and existing auth endpoints |
| CRUD and CSV | MainForm + generic EditorForm | Players/games/scores/export endpoints |
| Reflex Rush | GDI+ Panel, Forms timers, mouse events | GameEngine controls deadlines, tokens and scoring |
| Score charts | GDI+ bar charts on native Panels | Per-game leaderboard aggregation |
| HTTP explorer | Real HttpClient GET; status, JSON and latency | Same /api endpoints |
| Concurrency lab | Task.WhenAll over multiple HTTP requests | Store.reserve lock + transaction + trigger |
| Four playable seats | Start/play requests; live occupancy | GameEngine.start atomic admission |
| Admin monitoring | Round and audit DataGridViews | /api/play/sessions and /api/audit |

The dark/green/purple palette, sidebar, cards, table sections, HUD and board layout match the browser design language. Native system controls, corners and typography will not be pixel-identical. Optional web-game sound is not ported. Player/API identities and all rules are enforced by the server, not merely hidden controls.

## Runtime details

Backend sources and static assets copy to `bin/<configuration>/net8.0-windows/backend/` at build time. `desktop_host.py` stores data in `%LOCALAPPDATA%/ScoreForge/scoreforge.db`, shared by desktop instances. A separate Python server process is owned by each desktop process. SQLite's write transactions and triggers coordinate admission across those processes; the threading lock is per process. The launcher passes its parent process ID. On Windows the backend detects parent termination, allows up to 35 seconds for active rounds to finalize, then shuts down its own HTTP server. It does not kill another client's backend.

To import a web database, stop all clients and servers, wait for pending rounds to finish, back up both databases, and copy the web `data/scoreforge.db` into the desktop location before launch. This is file replacement, not a merge. Startup adds gameplay tables when needed. Original `START_HERE.bat` still launches the browser version with its original data directory.

Native requests use async/await so network waits do not block the UI. The lab creates concurrent outbound requests; server request threads still use the same critical-section protections. UI control updates occur on the WinForms UI synchronization context. The game polls at 700 ms and draws around every 33 ms; authoritative timing remains server-owned.

## Validation / limits

The Python regression suite and desktop source-structure checks are runnable in this authoring environment. A .NET SDK and Windows desktop runtime are absent, so **C# compilation, Visual Studio designer rendering and native UI behavior have not been verified here**. Static checks do not replace a build. On Windows:

1. Build Solution; open all three designers.
2. Sign in as admin and as player in separate application instances.
3. Play a full round; verify result saving and release.
4. Exercise CRUD, CSV, HTTP explorer, password change and session logout.
5. Run the 3- and 7-applicant lab; test five actual player instances for four-seat capacity.
6. Resize / DPI-check the form and use scrollbars where necessary.
7. Close the desktop process; confirm its backend exits after active rounds finish.

This is not an all-C# server conversion. If the instructor requires the backend itself in C#, an additional port is required. The previous Python guide remains useful for backend concepts; use this document for native client/Designer explanations.
