"""ScoreForge: threaded HTTP API + SQLite, using only Python's standard library."""
from __future__ import annotations
import argparse, csv, hashlib, hmac, io, json, math, mimetypes, os, secrets, sqlite3, threading, time
from contextlib import contextmanager
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
SESSION_SECONDS = 8 * 60 * 60
SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','player')), password TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), demo INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS games(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
 genre TEXT NOT NULL, max_score INTEGER NOT NULL CHECK(max_score > 0), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS scores(id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES users(id),
 game_id INTEGER NOT NULL REFERENCES games(id), points INTEGER NOT NULL CHECK(points >= 0),
 note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
CREATE TABLE IF NOT EXISTS rooms(id INTEGER PRIMARY KEY, name TEXT NOT NULL, capacity INTEGER NOT NULL DEFAULT 4 CHECK(capacity=4),
 demo INTEGER NOT NULL DEFAULT 0, owner_id INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS members(room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id), joined_at REAL NOT NULL, PRIMARY KEY(room_id,user_id));
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id),
 action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
CREATE INDEX IF NOT EXISTS idx_scores_player_game ON scores(player_id,game_id);
CREATE TRIGGER IF NOT EXISTS room_capacity BEFORE INSERT ON members
WHEN (SELECT COUNT(*) FROM members WHERE room_id=NEW.room_id) >= (SELECT capacity FROM rooms WHERE id=NEW.room_id)
BEGIN SELECT RAISE(ABORT,'Room is full'); END;
'''

class APIError(Exception):
    def __init__(self, status, message): self.status, self.message = status, message

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + '$' + hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 200_000).hex()

def password_matches(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split('$')[0]), encoded)

def clean(value, label, maximum=80, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise APIError(400, f'{label} must contain {minimum}–{maximum} characters.')
    return value.strip()

def integer(value, label, low=1, high=1_000_000_000):
    if type(value) is not int or not low <= value <= high: raise APIError(400, f'{label} must be an integer between {low} and {high}.')
    return value

class Store:
    def __init__(self, path, seed=True):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.room_lock = threading.Lock()  # serializes admission within this server process
        with self.connect() as db:
            db.executescript(SCHEMA)
            if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                db.execute('INSERT INTO users(username,name,role,password) VALUES(?,?,?,?)',
                           ('admin', 'Tournament admin', 'admin', password_hash(os.getenv('SCOREFORGE_ADMIN_PASSWORD','Admin@12345'))))
                if seed:
                    names = ['Mohamed Moustafa', 'Omar Ashraf', 'Omar Tharwat', 'Omar Sabry']
                    for i, name in enumerate(names, 1):
                        db.execute('INSERT INTO users(username,name,role,password) VALUES(?,?,?,?)', (f'player{i}',name,'player',password_hash('Player@12345')))
                    for i in range(1,9):
                        db.execute('INSERT INTO users(username,name,role,password,demo) VALUES(?,?,?,?,1)',
                                   (f'_demo{i}', f'Test player {i}', 'player', password_hash(secrets.token_urlsafe(24))))
                    db.executemany('INSERT INTO games(name,genre,max_score) VALUES(?,?,?)',
                                   [('Neon Sprint','Racing',10000),('Orbit Arena','Arcade',10000),('Logic Quest','Puzzle',1000)])
                    rows = [(2,1,8450,'Demo data'),(3,1,7920,'Demo data'),(4,1,7240,'Demo data'),(5,1,6810,'Demo data'),
                            (2,2,4280,'Demo data'),(3,2,6120,'Demo data'),(4,2,5390,'Demo data'),(5,2,3700,'Demo data'),
                            (2,3,860,'Demo data'),(3,3,780,'Demo data'),(4,3,940,'Demo data'),(5,3,710,'Demo data')]
                    db.executemany('INSERT INTO scores(player_id,game_id,points,note) VALUES(?,?,?,?)',rows)
            if not db.execute('SELECT 1 FROM rooms WHERE demo=0').fetchone():
                db.execute("INSERT INTO rooms(name) VALUES('Main arena')")

        from gameplay import GameEngine
        self.play = GameEngine(self, APIError)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level='DEFERRED')
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally: db.close()

    def query(self, sql, args=()):
        db = self.connect()
        try: return [dict(x) for x in db.execute(sql,args).fetchall()]
        finally: db.close()

    @staticmethod
    def audit(db, actor, action, detail):
        db.execute('INSERT INTO audit(actor_id,action,detail) VALUES(?,?,?)',(actor,action,detail))

    def reserve(self, room_id, player_id, actor_id, demo=False):
        # The read + capacity decision + insert share both a lock and a DB transaction.
        # BEGIN IMMEDIATE also protects against a second process using this database.
        with self.room_lock, self.transaction() as db:
            room = db.execute('SELECT * FROM rooms WHERE id=? AND demo=?',(room_id,int(demo))).fetchone()
            if not room: raise APIError(404,'Room not found.')
            if demo and room['owner_id'] != actor_id: raise APIError(403,'This demo belongs to another admin.')
            user = db.execute("SELECT id FROM users WHERE id=? AND active=1 AND role='player' AND demo=?",(player_id,int(demo))).fetchone()
            if not user: raise APIError(400,'An active player is required.')
            if db.execute('SELECT 1 FROM members WHERE room_id=? AND user_id=?',(room_id,player_id)).fetchone():
                return {'admitted':True,'already_joined':True,'message':'You already have a seat.'}
            count = db.execute('SELECT COUNT(*) FROM members WHERE room_id=?',(room_id,)).fetchone()[0]
            if count >= room['capacity']: raise APIError(409,'Arena full. All 4 seats are occupied.')
            db.execute('INSERT INTO members VALUES(?,?,?)',(room_id,player_id,time.time()))
            self.audit(db,actor_id,'DEMO_JOIN' if demo else 'JOIN',f'Player {player_id} → room {room_id}; seat {count+1}/4')
            return {'admitted':True,'already_joined':False,'seat':count+1,'message':f'Seat {count+1} secured.'}

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, store):
        super().__init__(address, Handler)
        self.store = store
        self.login_lock = threading.Lock()
        self.attempts = {}

    def service_actions(self):
        # Runs every server poll: finish rounds even after the browser is closed.
        try: self.store.play.sweep()
        except sqlite3.OperationalError: pass  # retry on the next tick

class Handler(BaseHTTPRequestHandler):
    server_version = 'ScoreForge/2.0'
    def log_message(self, format, *args): pass
    def respond(self, status, data, cookie=None, content_type='application/json; charset=utf-8'):
        body = json.dumps(data,ensure_ascii=False).encode() if content_type.startswith('application/json') else data
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError): pass

    def body(self):
        try: length = int(self.headers.get('Content-Length','0'))
        except ValueError: raise APIError(400,'Invalid content length.')
        if not 0 <= length <= 16384: raise APIError(413,'Request too large.')
        if length and self.headers.get('Content-Type','').split(';')[0] != 'application/json': raise APIError(415,'Use application/json.')
        try: value = json.loads(self.rfile.read(length) or b'{}')
        except (ValueError,UnicodeError): raise APIError(400,'Invalid JSON.')
        if not isinstance(value,dict): raise APIError(400,'JSON object required.')
        return value

    def auth(self, mutate=False, admin=False):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: raise APIError(401,'Sign in to continue.')
        self.token = cookie.get('sf_session').value if cookie.get('sf_session') else ''
        rows = self.server.store.query('''SELECT u.id,u.username,u.name,u.role,s.csrf FROM sessions s
            JOIN users u ON s.user_id=u.id WHERE token=? AND expires>? AND u.active=1''',
            (hashlib.sha256(self.token.encode()).hexdigest(),time.time()))
        if not rows: raise APIError(401,'Sign in to continue.')
        user=rows[0]
        if admin and user['role'] != 'admin': raise APIError(403,'Administrator access required.')
        if mutate and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),user['csrf']): raise APIError(403,'Invalid security token. Refresh and try again.')
        return user

    def do_GET(self): self.handle_request('GET')
    def do_POST(self): self.handle_request('POST')
    def do_PUT(self): self.handle_request('PUT')
    def do_DELETE(self): self.handle_request('DELETE')

    def handle_request(self, method):
        try: self.route(method)
        except APIError as e: self.respond(e.status,{'error':e.message})
        except sqlite3.IntegrityError: self.respond(409,{'error':'This record is duplicated, in use, or violates a data constraint.'})
        except sqlite3.OperationalError: self.respond(503,{'error':'Database busy or unavailable. Please retry.'})
        except Exception:
            import traceback; traceback.print_exc()
            self.respond(500,{'error':'Unexpected server error.'})

    def route(self, method):
        path = urlsplit(self.path).path
        st = self.server.store
        if not path.startswith('/api/'):
            if method != 'GET': raise APIError(405,'Method not allowed.')
            files = {'/':'index.html','/login':'index.html','/admin':'index.html','/player':'index.html',
                     '/app.js':'app.js','/style.css':'style.css','/favicon.svg':'favicon.svg'}
            if path not in files: raise APIError(404,'Page not found.')
            p=ROOT/'static'/files[path]
            return self.respond(200,p.read_bytes(),content_type=mimetypes.guess_type(str(p))[0] or 'text/plain')
        if method != 'GET':
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host',''): raise APIError(403,'Cross-origin requests are not allowed.')
        data = self.body() if method != 'GET' else {}
        if path == '/api/login' and method == 'POST':
            username=clean(data.get('username'),'Username',32)
            password=clean(data.get('password'),'Password',128)
            key=self.client_address[0]
            with self.server.login_lock:
                now=time.time()
                self.server.attempts={k:v for k,v in self.server.attempts.items() if v[1]>now}
                count,until=self.server.attempts.get(key,(0,now+60))
                if count>=20: raise APIError(429,'Too many login attempts. Wait one minute.')
                self.server.attempts[key]=(count+1,until)
            rows=st.query('SELECT * FROM users WHERE username=? AND active=1 AND demo=0',(username,))
            if not rows or not password_matches(password,rows[0]['password']): raise APIError(401,'Incorrect username or password.')
            u=rows[0]; token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
            with st.transaction() as db:
                db.execute('DELETE FROM sessions WHERE expires<=?',(time.time(),))
                db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],csrf,time.time()+SESSION_SECONDS))
                st.audit(db,u['id'],'LOGIN',u['username'])
            return self.respond(200,{'user':{k:u[k] for k in ('id','username','name','role')},'csrf':csrf},
                                f'sf_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}')
        u=self.auth(mutate=method!='GET')
        if path=='/api/me' and method=='GET': return self.respond(200,{'user':{k:v for k,v in u.items() if k!='csrf'},'csrf':u['csrf']})
        if path=='/api/logout' and method=='POST':
            with st.transaction() as db:
                db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(self.token.encode()).hexdigest(),))
                # Leaving is explicit: logout does not remove another browser's arena membership.
            return self.respond(200,{'message':'Signed out.'},'sf_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
        if path=='/api/password' and method=='POST':
            old=clean(data.get('current'),'Current password',128); new=clean(data.get('password'),'New password',128,10)
            with st.transaction() as db:
                encoded=db.execute('SELECT password FROM users WHERE id=?',(u['id'],)).fetchone()[0]
                if not password_matches(old,encoded): raise APIError(400,'Current password is incorrect.')
                db.execute('UPDATE users SET password=? WHERE id=?',(password_hash(new),u['id']))
                db.execute('DELETE FROM sessions WHERE user_id=? AND token<>?',(u['id'],hashlib.sha256(self.token.encode()).hexdigest()))
                st.audit(db,u['id'],'PASSWORD_CHANGE','Other sessions revoked')
            return self.respond(200,{'message':'Password updated.'})
        if path=='/api/players' and method=='GET':
            rows=st.query("SELECT id,name,username,active FROM users WHERE role='player' AND demo=0 ORDER BY name")
            if u['role']!='admin': rows=[{k:v for k,v in x.items() if k!='username'} for x in rows if x['active']]
            return self.respond(200,{'players':rows})
        if path.startswith('/api/players/') and method=='GET':
            pid=self.path_id(path)
            rows=st.query("SELECT id,name,active FROM users WHERE id=? AND role='player' AND demo=0",(pid,))
            if not rows: raise APIError(404,'Player not found.')
            return self.respond(200,{'player':rows[0]})
        if path=='/api/games' and method=='GET': return self.respond(200,{'games':st.query('SELECT * FROM games ORDER BY name')})
        if path=='/api/scores' and method=='GET':
            rows=st.query('''SELECT s.*,u.name AS player,g.name AS game FROM scores s JOIN users u ON u.id=s.player_id
                             JOIN games g ON g.id=s.game_id ORDER BY s.id DESC''')
            if u['role']!='admin': rows=[x for x in rows if x['player_id']==u['id']]
            return self.respond(200,{'scores':rows})
        if path=='/api/leaderboard' and method=='GET':
            rows=st.query('''SELECT u.id AS player_id,u.name,g.id AS game_id,g.name AS game,MAX(s.points) AS best,
                        COUNT(*) AS plays,ROUND(AVG(s.points),1) AS average FROM scores s JOIN users u ON s.player_id=u.id
                        JOIN games g ON g.id=s.game_id GROUP BY u.id,g.id ORDER BY g.id,best DESC,u.name''')
            previous={}; ranks={}
            for row in rows:
                gid=row['game_id']; ranks[gid]=ranks.get(gid,0)+1
                if previous.get(gid,(None,None))[0] != row['best']: previous[gid]=(row['best'],ranks[gid])
                row['rank']=previous[gid][1]
            return self.respond(200,{'leaderboard':rows})
        if path.startswith('/api/play/'):
            if path=='/api/play/sessions' and method=='GET':
                if u['role']!='admin': raise APIError(403,'Administrator access required.')
                return self.respond(200,st.play.sessions())
            if u['role']!='player': raise APIError(403,'Sign in as a player to play Reflex Rush.')
            if path=='/api/play/state' and method=='GET': return self.respond(200,st.play.snapshot(u['id']))
            if path=='/api/play/start' and method=='POST': return self.respond(200,st.play.start(u['id'],data.get('mode','normal')))
            if path in ('/api/play/hit','/api/play/miss') and method=='POST':
                return self.respond(200,st.play.action(u['id'],data.get('round_id'),data.get('target_id'),path.endswith('/hit')))
            if path=='/api/play/cancel' and method=='POST': return self.respond(200,st.play.cancel(u['id']))
            raise APIError(404,'Gameplay endpoint not found.')
        if path=='/api/rooms' and method=='GET':
            st.play.sweep()
            return self.respond(200,{'rooms':self.rooms(False)})
        if path in ('/api/rooms/join','/api/rooms/leave') and method=='POST':
            if u['role']!='player': raise APIError(403,'Only players can join the live arena.')
            rid=integer(data.get('room_id'),'Room ID')
            if path.endswith('/join'): return self.respond(200,st.reserve(rid,u['id'],u['id']))
            with st.transaction() as db:
                if not db.execute('SELECT 1 FROM rooms WHERE id=? AND demo=0',(rid,)).fetchone(): raise APIError(404,'Room not found.')
                db.execute("UPDATE rounds SET status='cancelled' WHERE user_id=? AND room_id=? AND status='active'",(u['id'],rid))
                db.execute('DELETE FROM members WHERE room_id=? AND user_id=?',(rid,u['id']))
                st.audit(db,u['id'],'LEAVE',f'Room {rid}')
            return self.respond(200,{'message':'Seat released.'})
        # Everything below is administrative; authorization is enforced server-side.
        if u['role']!='admin': raise APIError(403,'Administrator access required.')
        if path=='/api/audit' and method=='GET':
            return self.respond(200,{'events':st.query('SELECT a.*,u.name AS actor FROM audit a LEFT JOIN users u ON a.actor_id=u.id ORDER BY a.id DESC LIMIT 100')})
        if path=='/api/export' and method=='GET':
            output=io.StringIO(); writer=csv.writer(output); writer.writerow(['ID','Player','Game','Points','Date','Note'])
            for row in st.query('SELECT s.id,u.name,g.name AS game,s.points,s.created_at,s.note FROM scores s JOIN users u ON s.player_id=u.id JOIN games g ON s.game_id=g.id ORDER BY s.id'):
                writer.writerow([("'"+str(v)) if str(v).startswith(('=','+','-','@','\t','\r','\n')) else v for v in row.values()])
            return self.respond(200,output.getvalue().encode('utf-8-sig'),content_type='text/csv; charset=utf-8')
        if path=='/api/demo/start' and method=='POST':
            ids=[x['id'] for x in st.query('SELECT id FROM users WHERE demo=1 ORDER BY id')]
            if len(ids)<8: raise APIError(400,'Demo accounts unavailable. This database was initialized without demo data.')
            with st.transaction() as db:
                db.execute('DELETE FROM rooms WHERE demo=1 AND owner_id=?',(u['id'],))
                rid=db.execute("INSERT INTO rooms(name,demo,owner_id) VALUES('Concurrency lab',1,?)",(u['id'],)).lastrowid
            first=st.reserve(rid,ids[0],u['id'],True)
            return self.respond(201,{'room_id':rid,'players':ids[1:],'initial':first,'capacity':4})
        if path=='/api/demo/join' and method=='POST':
            return self.respond(200,st.reserve(integer(data.get('room_id'),'Room ID'),integer(data.get('player_id'),'Player ID'),u['id'],True))
        if path=='/api/demo/state' and method=='GET': return self.respond(200,{'rooms':self.rooms(True,u['id'])})
        if path=='/api/rooms/reset' and method=='POST':
            rid=integer(data.get('room_id'),'Room ID')
            with st.transaction() as db:
                db.execute("UPDATE rounds SET status='cancelled' WHERE room_id=? AND status='active'",(rid,))
                db.execute('DELETE FROM members WHERE room_id=? AND room_id IN (SELECT id FROM rooms WHERE demo=0)',(rid,))
                st.audit(db,u['id'],'RESET_ROOM',f'Room {rid}')
            return self.respond(200,{'message':'All arena seats released.'})
        if path=='/api/players' and method=='POST':
            name=clean(data.get('name'),'Name'); username=clean(data.get('username'),'Username',32)
            if not all(c.isascii() and (c.isalnum() or c in '._-') for c in username): raise APIError(400,'Username: use letters, digits, dots, underscores or hyphens.')
            password=clean(data.get('password'),'Password',128,10)
            with st.transaction() as db:
                pid=db.execute("INSERT INTO users(name,username,role,password) VALUES(?,?,'player',?)",(name,username,password_hash(password))).lastrowid
                st.audit(db,u['id'],'CREATE_PLAYER',f'Player {pid}')
            return self.respond(201,{'id':pid,'message':'Player created.'})
        if path.startswith('/api/players/') and method in ('PUT','DELETE'):
            pid=self.path_id(path)
            with st.transaction() as db:
                if not db.execute("SELECT 1 FROM users WHERE id=? AND role='player' AND demo=0",(pid,)).fetchone(): raise APIError(404,'Player not found.')
                if method=='DELETE': db.execute('DELETE FROM users WHERE id=?',(pid,))
                else:
                    active=integer(data.get('active'),'Active',0,1)
                    db.execute('UPDATE users SET name=?,active=? WHERE id=?',(clean(data.get('name'),'Name'),active,pid))
                    if not active:
                        db.execute("UPDATE rounds SET status='cancelled' WHERE user_id=? AND status='active'",(pid,))
                        db.execute('DELETE FROM sessions WHERE user_id=?',(pid,)); db.execute('DELETE FROM members WHERE user_id=?',(pid,))
                st.audit(db,u['id'],method+'_PLAYER',f'Player {pid}')
            return self.respond(200,{'message':'Player updated.' if method=='PUT' else 'Player deleted.'})
        if (path=='/api/games' and method=='POST') or (path.startswith('/api/games/') and method in ('PUT','DELETE')):
            gid=self.path_id(path) if path!='/api/games' else None
            with st.transaction() as db:
                if gid and not db.execute('SELECT 1 FROM games WHERE id=?',(gid,)).fetchone(): raise APIError(404,'Game not found.')
                if method=='DELETE': db.execute('DELETE FROM games WHERE id=?',(gid,))
                else:
                    values=(clean(data.get('name'),'Game name'),clean(data.get('genre'),'Genre',40),integer(data.get('max_score'),'Maximum score'),integer(data.get('active',1),'Active',0,1))
                    if gid:
                        if db.execute('SELECT 1 FROM play_modes WHERE game_id=?',(gid,)).fetchone() and values[2] != 1000000: raise APIError(400,'Reflex Rush score limit is fixed; you can rename or archive the game.')
                        if db.execute('SELECT 1 FROM scores WHERE game_id=? AND points>?',(gid,values[2])).fetchone(): raise APIError(400,'Maximum cannot be lower than an existing score.')
                        db.execute('UPDATE games SET name=?,genre=?,max_score=?,active=? WHERE id=?',values+(gid,))
                    else: gid=db.execute('INSERT INTO games(name,genre,max_score,active) VALUES(?,?,?,?)',values).lastrowid
                st.audit(db,u['id'],method+'_GAME',f'Game {gid}')
            return self.respond(201 if method=='POST' else 200,{'id':gid,'message':'Game saved.' if method!='DELETE' else 'Game deleted.'})
        if (path=='/api/scores' and method=='POST') or (path.startswith('/api/scores/') and method in ('PUT','DELETE')):
            sid=self.path_id(path) if path!='/api/scores' else None
            with st.transaction() as db:
                if sid and not db.execute('SELECT 1 FROM scores WHERE id=?',(sid,)).fetchone(): raise APIError(404,'Score not found.')
                if method=='DELETE': db.execute('DELETE FROM scores WHERE id=?',(sid,))
                else:
                    pid=integer(data.get('player_id'),'Player'); gid=integer(data.get('game_id'),'Game'); points=integer(data.get('points'),'Points',0)
                    if not db.execute("SELECT 1 FROM users WHERE id=? AND role='player' AND active=1 AND demo=0",(pid,)).fetchone(): raise APIError(400,'Select an active player.')
                    if method=='POST' and db.execute('SELECT 1 FROM play_modes WHERE game_id=?',(gid,)).fetchone(): raise APIError(400,'Reflex Rush scores are earned by playing, not entered manually.')
                    game=db.execute('SELECT * FROM games WHERE id=? AND active=1',(gid,)).fetchone()
                    if not game or points>game['max_score']: raise APIError(400,'Select an active game and a score within its maximum.')
                    values=(pid,gid,points,clean(data.get('note',''),'Note',250,0))
                    if sid: db.execute('UPDATE scores SET player_id=?,game_id=?,points=?,note=? WHERE id=?',values+(sid,))
                    else: sid=db.execute('INSERT INTO scores(player_id,game_id,points,note) VALUES(?,?,?,?)',values).lastrowid
                st.audit(db,u['id'],method+'_SCORE',f'Score {sid}')
            return self.respond(201 if method=='POST' else 200,{'id':sid,'message':'Score saved.' if method!='DELETE' else 'Score deleted.'})
        raise APIError(404,'Endpoint not found.')

    def rooms(self,demo,owner=None):
        rooms=self.server.store.query('SELECT * FROM rooms WHERE demo=?'+(' AND owner_id=?' if demo else ''),(int(demo),owner) if demo else (0,))
        for room in rooms:
            room['members']=self.server.store.query('SELECT u.id,u.name,m.joined_at FROM members m JOIN users u ON u.id=m.user_id WHERE room_id=? ORDER BY joined_at',(room['id'],))
            room['occupied']=len(room['members'])
        return rooms

    @staticmethod
    def path_id(path):
        try: return integer(int(path.rsplit('/',1)[-1]),'ID')
        except ValueError: raise APIError(400,'Invalid ID.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='ScoreForge local web application')
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--db',default=str(ROOT/'data'/'scoreforge.db')); parser.add_argument('--no-demo',action='store_true')
    args=parser.parse_args()
    server=Server((args.host,args.port),Store(args.db,seed=not args.no_demo))
    print(f'ScoreForge is running at http://{args.host}:{server.server_port} — Ctrl+C to stop.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nServer stopped.')
    finally: server.server_close()
