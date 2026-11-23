# Presentation walkthrough · approximately 6 minutes

## 1. Introduce the project · 30 seconds

**English:** “ScoreForge is a game score management system. It combines a graphical web interface, database-backed scores and charts, role-based authentication, and synchronized player admission.”

**المصري:** المشروع بيدير اللاعبين والألعاب والدرجات، وبيعرض ترتيب ورسوم بيانية، وكل ده مرتبط بقاعدة بيانات. وفيه تسجيل دخول بصلاحيات مختلفة وتنظيم للدخول المتزامن.

## 2. Login and roles · 45 seconds

Open the admin account. Show Players, Games, Score history, Activity log. In a private/incognito window, sign in as player1. Show that it opens the player workspace and has no score-management controls. Explain that API permissions are enforced on the server too.

**المصري:** الأدمن عنده وظائف الإدارة. اللاعب بيشوف درجاته ويحجز مكان. التحقق مش في شكل الصفحة بس؛ السيرفر نفسه بيرفض الطلب اللي مش مسموح للحساب يعمله.

## 3. Play a real round · 45 seconds

In the player window, open Play Reflex Rush. Choose Normal, press Start round, and click the glowing targets. After 30 seconds, show the saved result and released seat. Click View ranking; the new score appears in the Normal leaderboard. Switch to admin → Play Reflex Rush to see the completed session.

**المصري:** اللاعب هنا بيلعب فعلًا، والنتيجة بتتسجل تلقائيًا. الوقت والنقط بيتحسبوا على السيرفر. كل مستوى صعوبة ليه ترتيب منفصل. لما الجولة تخلص، المكان بيفضى للاعب تاني.

## 4. Database and graphics · 60 seconds

Create a score for a non-Reflex catalog game, below that game's maximum. Reflex Rush scores come from gameplay. Show it in Score history. Open Leaderboard and select the same game, then Analytics. Edit or delete the score to demonstrate CRUD. Explain that an archived game keeps historical results.

**المصري:** الدرجة الجديدة بتتسجل في قاعدة البيانات وبتظهر في السجل والترتيب والرسم البياني. الترتيب بأفضل درجة داخل نفس اللعبة؛ الدرجات المتساوية بتاخد نفس المركز.

## 5. HTTP networking · 60 seconds

Open HTTP explorer. Send GET /api/players. Show status 200, elapsed time, and JSON. Switch to one player and enter an existing ID. Try a nonexistent ID to show 404. Optionally use the browser Network panel to independently inspect the requests.

**المصري:** المتصفح هنا عميل، والسيرفر بيرد عليه بطلب شبكة حقيقي. بيقرأ البيانات من قاعدة البيانات ويرجعها في رد منظم، مش بيانات ثابتة متحطوطة في الصفحة.

## 6. Synchronization · 90 seconds

Open Concurrency lab. Explain the starting condition: capacity 4, already occupied 1.

1. Select 3 applicants. Run: all three should receive 200; final occupancy is 4.
2. Select 7 applicants. Run: three receive 200, four receive 409; final occupancy is still 4.
3. Show that the live room was not changed by the test.

**English:** “A race condition occurs when requests separately check a shared count before any has reserved a seat. Our lock and transaction make the check and insert atomic. The server handles multiple threads, but only one enters this critical section at a time.”

**المصري:** لو كل طلب عدّ الموجودين لوحده وبعدين حجز، ممكن الطلبات تتسابق وتزوّد العدد. القفل والمعاملة بيخلّوا العدّ والحجز خطوة واحدة محمية. ده مش معناه إن السيرفر كله مسار واحد؛ الجزء الحساس بس هو اللي بيتنفذ بالترتيب.

## 7. Tests and persistence · 45 seconds

Run RUN_TESTS.bat. Explain that the tests use a temporary database and real HTTP connections. Restart the app to show records persist. Demonstrate Leave or Reset to release seats.

## Questions to prepare for

| Question | Answer |
|---|---|
| Is synchronization the same as multithreading? | No. Threads allow concurrent handling; synchronization protects shared state. |
| Why use a database transaction if there is a lock? | The lock protects threads in this process; the transaction protects database writers, including another process. |
| Why return HTTP 409? | The request is valid, but conflicts with the current full-room state. |
| Can a player submit another player's ID to take their seat? | No. Live admission uses the authenticated session identity. |
| What if the same request is sent twice? | A repeated join succeeds idempotently without creating another membership. |
| Is the earliest applicant guaranteed a seat? | No FIFO guarantee; the maximum count is guaranteed by the admission path. |
| Why not sum all games for one ranking? | Different games use different scoring scales. Rankings are per game. |
| Is it ready for public hosting? | It is designed and tested as a local classroom project, not an internet production service. |
