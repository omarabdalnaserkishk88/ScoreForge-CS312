"""Server-owned Reflex Rush rounds, scoring, deadlines and arena admission."""
import secrets
import time

MODES = {
    'easy': {'name':'Easy', 'lifetime':2.5, 'size':76},
    'normal': {'name':'Normal', 'lifetime':1.6, 'size':58},
    'hard': {'name':'Hard', 'lifetime':1.0, 'size':42},
}
DURATION = 30
SCHEMA = '''
CREATE TABLE IF NOT EXISTS play_modes(mode TEXT PRIMARY KEY, game_id INTEGER NOT NULL UNIQUE REFERENCES games(id));
CREATE TABLE IF NOT EXISTS rounds(
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), room_id INTEGER NOT NULL REFERENCES rooms(id),
 game_id INTEGER NOT NULL REFERENCES games(id), mode TEXT NOT NULL,
 started REAL NOT NULL, deadline REAL NOT NULL, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','finished','cancelled')),
 points INTEGER NOT NULL DEFAULT 0, hits INTEGER NOT NULL DEFAULT 0, misses INTEGER NOT NULL DEFAULT 0,
 combo INTEGER NOT NULL DEFAULT 0, best_combo INTEGER NOT NULL DEFAULT 0, reaction_total REAL NOT NULL DEFAULT 0,
 target TEXT NOT NULL, x INTEGER NOT NULL, y INTEGER NOT NULL, issued REAL NOT NULL,
 score_id INTEGER REFERENCES scores(id) ON DELETE SET NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_round_per_player ON rounds(user_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS round_deadlines ON rounds(status,deadline);
'''

class GameEngine:
    def __init__(self,store,error):
        self.store,self.error,self.clock=store,error,time.time
        db=store.connect()
        try:
            db.executescript(SCHEMA)
            for mode,settings in MODES.items():
                if not db.execute('SELECT 1 FROM play_modes WHERE mode=?',(mode,)).fetchone():
                    name='Reflex Rush · '+settings['name']
                    db.execute('INSERT OR IGNORE INTO games(name,genre,max_score) VALUES(?,?,?)',(name,'Reaction',1000000))
                    gid=db.execute('SELECT id FROM games WHERE name=?',(name,)).fetchone()[0]
                    db.execute('INSERT INTO play_modes VALUES(?,?)',(mode,gid))
            db.commit()
        finally:db.close()

    @staticmethod
    def next_target(db,rid,now):
        # Normalized coordinates in 0..1000; frontend keeps targets inside safe margins.
        db.execute('UPDATE rounds SET target=?,x=?,y=?,issued=? WHERE id=?',
                   (secrets.token_urlsafe(20),secrets.randbelow(1001),secrets.randbelow(1001),now,rid))

    def finish_expired(self,db,now):
        for r in db.execute("SELECT * FROM rounds WHERE status='active' AND deadline<=?",(now,)).fetchall():
            score_id=db.execute('INSERT INTO scores(player_id,game_id,points,note) VALUES(?,?,?,?)',
                (r['user_id'],r['game_id'],r['points'],f"Reflex Rush | {r['mode']} | {r['hits']} hits | {r['misses']} misses | round {r['id']}")).lastrowid
            db.execute("UPDATE rounds SET status='finished',score_id=? WHERE id=?",(score_id,r['id']))
            db.execute('DELETE FROM members WHERE room_id=? AND user_id=?',(r['room_id'],r['user_id']))
            self.store.audit(db,r['user_id'],'ROUND_FINISHED',f"{r['mode']}: {r['points']} points; score {score_id}")

    def sweep(self):
        now=self.clock()
        # Avoid acquiring SQLite's writer lock on every service tick when nothing expired.
        if self.store.query("SELECT 1 FROM rounds WHERE status='active' AND deadline<=? LIMIT 1",(now,)):
            with self.store.room_lock,self.store.transaction() as db:self.finish_expired(db,now)

    def view(self,db,r,now):
        if not r:return None
        result={k:r[k] for k in ('id','mode','status','points','hits','misses','combo','best_combo','score_id','game_id')}
        result.update(remaining=max(0,r['deadline']-now),duration=DURATION,
                      accuracy=round(100*r['hits']/max(1,r['hits']+r['misses']),1),
                      average_ms=round(r['reaction_total']/r['hits']) if r['hits'] else 0)
        if r['status']=='active':
            result['target']={'id':r['target'],'x':r['x'],'y':r['y'],'size':MODES[r['mode']]['size'],
                              'remaining':max(0,MODES[r['mode']]['lifetime']-(now-r['issued']))}
        return result

    def snapshot(self,uid):
        now=self.clock()
        with self.store.room_lock,self.store.transaction() as db:
            self.finish_expired(db,now)
            r=db.execute('SELECT * FROM rounds WHERE user_id=? ORDER BY started DESC,rowid DESC LIMIT 1',(uid,)).fetchone()
            if r and r['status']=='active' and now-r['issued']>=MODES[r['mode']]['lifetime']:
                db.execute('UPDATE rounds SET misses=misses+1,combo=0 WHERE id=?',(r['id'],))
                self.next_target(db,r['id'],now)
                r=db.execute('SELECT * FROM rounds WHERE id=?',(r['id'],)).fetchone()
            return {'round':self.view(db,r,now),'modes':MODES}

    def start(self,uid,mode):
        if not isinstance(mode,str) or mode not in MODES:raise self.error(400,'Choose Easy, Normal, or Hard.')
        now=self.clock()
        with self.store.room_lock,self.store.transaction() as db:
            self.finish_expired(db,now)
            existing=db.execute("SELECT * FROM rounds WHERE user_id=? AND status='active'",(uid,)).fetchone()
            if existing:return {'round':self.view(db,existing,now),'resumed':True}
            if not db.execute("SELECT 1 FROM users WHERE id=? AND role='player' AND active=1 AND demo=0",(uid,)).fetchone():raise self.error(403,'Active player account required.')
            game=db.execute('SELECT g.* FROM games g JOIN play_modes p ON p.game_id=g.id WHERE p.mode=?',(mode,)).fetchone()
            if not game or not game['active']:raise self.error(409,'This difficulty is currently archived by the administrator.')
            room=db.execute('SELECT * FROM rooms WHERE demo=0 ORDER BY id LIMIT 1').fetchone()
            if not room:raise self.error(404,'Live arena unavailable.')
            member=db.execute('SELECT 1 FROM members WHERE room_id=? AND user_id=?',(room['id'],uid)).fetchone()
            if not member:
                count=db.execute('SELECT COUNT(*) FROM members WHERE room_id=?',(room['id'],)).fetchone()[0]
                if count>=4:raise self.error(409,'Arena full — four seats are occupied. Try again when a seat is released.')
                db.execute('INSERT INTO members VALUES(?,?,?)',(room['id'],uid,now))
            rid=secrets.token_urlsafe(18)
            db.execute('''INSERT INTO rounds(id,user_id,room_id,game_id,mode,started,deadline,target,x,y,issued)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                       (rid,uid,room['id'],game['id'],mode,now,now+DURATION,'',0,0,now))
            self.next_target(db,rid,now)
            self.store.audit(db,uid,'ROUND_STARTED',f'{mode}: {rid}')
            r=db.execute('SELECT * FROM rounds WHERE id=?',(rid,)).fetchone()
            return {'round':self.view(db,r,now),'resumed':False}

    def action(self,uid,rid,target,hit):
        if not isinstance(rid,str) or not isinstance(target,str):raise self.error(400,'Round and target IDs are required.')
        now=self.clock()
        with self.store.room_lock,self.store.transaction() as db:
            self.finish_expired(db,now)
            r=db.execute('SELECT * FROM rounds WHERE id=? AND user_id=?',(rid,uid)).fetchone()
            if not r:raise self.error(404,'Round not found.')
            if r['status']!='active':return {'round':self.view(db,r,now),'outcome':r['status']}
            if not secrets.compare_digest(r['target'],target):raise self.error(409,'Target already used. Synchronizing your round.')
            elapsed=now-r['issued']
            # Client never sends a score. Server accepts one event per challenge token.
            if elapsed<0.08:raise self.error(429,'Too fast. Wait for the next target update.')
            accepted=hit and elapsed<MODES[r['mode']]['lifetime']
            if accepted:
                combo=r['combo']+1
                gained=100+min(100,(combo-1)*10)
                db.execute('''UPDATE rounds SET points=points+?,hits=hits+1,combo=?,best_combo=MAX(best_combo,?),
                              reaction_total=reaction_total+? WHERE id=?''',(gained,combo,combo,elapsed*1000,rid))
            else:
                gained=0
                db.execute('UPDATE rounds SET misses=misses+1,combo=0 WHERE id=?',(rid,))
            self.next_target(db,rid,now)
            r=db.execute('SELECT * FROM rounds WHERE id=?',(rid,)).fetchone()
            return {'round':self.view(db,r,now),'outcome':'hit' if accepted else 'miss','gained':gained}

    def cancel(self,uid):
        now=self.clock()
        with self.store.room_lock,self.store.transaction() as db:
            self.finish_expired(db,now)
            r=db.execute("SELECT * FROM rounds WHERE user_id=? AND status='active'",(uid,)).fetchone()
            if r:
                db.execute("UPDATE rounds SET status='cancelled' WHERE id=?",(r['id'],))
                db.execute('DELETE FROM members WHERE room_id=? AND user_id=?',(r['room_id'],uid))
                self.store.audit(db,uid,'ROUND_CANCELLED',r['id'])
        return {'message':'Round stopped. No score saved; seat released.'}

    def sessions(self):
        self.sweep()
        return {'sessions':self.store.query('''SELECT r.id,u.name,r.mode,r.status,r.points,r.hits,r.misses,
            r.started,r.deadline,r.score_id FROM rounds r JOIN users u ON u.id=r.user_id ORDER BY started DESC LIMIT 100''')}
