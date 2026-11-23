"""Actual HTTP gameplay checks with a controlled server clock (no 30-second sleeps)."""
import concurrent.futures
from pathlib import Path
import tempfile
import threading
import time
import unittest
import test_system
from server import Store, Server

class GameplayTests(unittest.TestCase):
    request=classmethod(test_system.IntegrationTests.request.__func__)
    login=classmethod(test_system.IntegrationTests.login.__func__)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'game.db';self.store=Store(self.db)
        self.now=time.time();self.store.play.clock=lambda:self.now
        self.server=Server(('127.0.0.1',0),self.store)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        # Helpers use class attributes, matching their shared real HTTP client.
        type(self).server=self.server
        self.admin=self.login('admin','Admin@12345');self.p=self.login('player1','Player@12345')

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def start(self,session=None,mode='normal'):
        status,data,_=self.request('/api/play/start','POST',{'mode':mode},session or self.p)
        self.assertEqual(status,200,data);return data['round']

    def hit(self,r,hit=True,session=None):
        self.now+=.2
        return self.request('/api/play/'+('hit' if hit else 'miss'),'POST',{'round_id':r['id'],'target_id':r['target']['id'],'points':999999999},session or self.p)

    def test_score_combo_miss_expiry_and_exactly_once_save(self):
        r=self.start();self.assertEqual(r['points'],0)
        status,data,_=self.hit(r);self.assertEqual(status,200);r=data['round'];self.assertEqual(r['points'],100)
        _,data,_=self.hit(r);r=data['round'];self.assertEqual(r['points'],210)
        _,data,_=self.hit(r,False);r=data['round'];self.assertEqual(r['combo'],0);self.assertEqual(r['misses'],1)
        self.now+=31
        self.store.play.sweep() # simulates server service tick with no browser request
        _,data,_=self.request('/api/play/state',session=self.p);r=data['round']
        self.assertEqual(r['status'],'finished');self.assertEqual(r['points'],210)
        self.assertEqual(len(self.store.query('SELECT * FROM scores WHERE id=?',(r['score_id'],))),1)
        self.assertEqual(self.store.query('SELECT * FROM members WHERE user_id=?',(self.p['id'],)),[])
        before=len(self.store.query('SELECT * FROM scores'))
        for _ in range(3):self.request('/api/play/state',session=self.p);self.store.play.sweep()
        self.assertEqual(len(self.store.query('SELECT * FROM scores')),before)
        rank=self.request('/api/leaderboard',session=self.p)[1]['leaderboard']
        self.assertEqual([x['best'] for x in rank if x['game_id']==r['game_id']],[210])

    def test_target_replay_ownership_and_rate_limit(self):
        r=self.start();body={'round_id':r['id'],'target_id':r['target']['id']}
        self.assertEqual(self.request('/api/play/hit','POST',body,self.p)[0],429)
        other=self.login('player2','Player@12345');self.now+=.2
        self.assertEqual(self.request('/api/play/hit','POST',body,other)[0],404)
        self.assertEqual(self.request('/api/play/hit','POST',body,self.p)[0],200)
        self.assertEqual(self.request('/api/play/hit','POST',body,self.p)[0],409)
        self.assertEqual(self.request('/api/play/start','POST',{},self.admin)[0],403)
        self.assertEqual(self.request('/api/play/sessions',session=self.p)[0],403)
        self.assertEqual(self.request('/api/play/start','POST',{'mode':'impossible'},self.p)[0],400)

    def test_four_round_capacity_and_fifth_retry(self):
        sessions=[self.p]+[self.login(f'player{i}','Player@12345') for i in range(2,5)]
        self.request('/api/players','POST',{'name':'Fifth','username':'fifth','password':'Player@12345'},self.admin)
        sessions.append(self.login('fifth','Player@12345'));gate=threading.Barrier(5)
        def start(s):
            gate.wait();return self.request('/api/play/start','POST',{'mode':'easy'},s)[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:statuses=list(pool.map(start,sessions))
        self.assertEqual(statuses.count(200),4);self.assertEqual(statuses.count(409),1)
        self.assertEqual(len(self.store.query("SELECT * FROM rounds WHERE status='active'")),4)
        self.assertEqual(len(self.store.query('SELECT * FROM members WHERE room_id=1')),4)
        self.now+=31;self.store.play.sweep()
        self.assertEqual(self.request('/api/play/start','POST',{'mode':'hard'},sessions[statuses.index(409)])[0],200)

    def test_resume_cancel_leave_and_reset(self):
        r=self.start();status,data,_=self.request('/api/play/start','POST',{'mode':'hard'},self.p)
        self.assertEqual(data['round']['id'],r['id']);self.assertTrue(data['resumed'])
        self.assertEqual(self.request('/api/play/state',session=self.p)[1]['round']['id'],r['id'])
        self.request('/api/play/cancel','POST',{},self.p)
        self.assertEqual(self.request('/api/play/state',session=self.p)[1]['round']['status'],'cancelled')
        self.now+=1;r=self.start()
        self.request('/api/rooms/leave','POST',{'room_id':1},self.p)
        self.assertEqual(self.request('/api/play/state',session=self.p)[1]['round']['status'],'cancelled')
        self.now+=1;r=self.start()
        self.request('/api/rooms/reset','POST',{'room_id':1},self.admin)
        self.assertEqual(self.request('/api/play/state',session=self.p)[1]['round']['status'],'cancelled')
        self.assertEqual(self.store.query('SELECT * FROM scores WHERE game_id=?',(r['game_id'],)),[])

    def test_expired_target_and_difficulty_isolation(self):
        ids=[]
        for mode in ('easy','normal','hard'):
            r=self.start(mode=mode);ids.append(r['game_id']);self.now+=3
            _,data,_=self.request('/api/play/state',session=self.p)
            self.assertEqual(data['round']['misses'],1)
            self.assertNotEqual(r['target']['id'],data['round']['target']['id'])
            self.request('/api/play/cancel','POST',{},self.p);self.now+=1
        self.assertEqual(len(set(ids)),3)

    def test_existing_database_upgrade_preserves_scores(self):
        before=self.store.query('SELECT * FROM scores');r=self.start();self.hit(r)
        restarted=Store(self.db)
        self.assertEqual(restarted.query('SELECT * FROM scores'),before)
        self.assertEqual(len(restarted.query('SELECT * FROM play_modes')),3)
        restarted.play.clock=lambda:self.now+31;restarted.play.sweep()
        self.assertEqual(len(restarted.query('SELECT * FROM scores')),len(before)+1)

    def test_archived_mode_manual_score_and_disable(self):
        r=self.start();gid=r['game_id'];self.request('/api/play/cancel','POST',{},self.p)
        self.assertEqual(self.request('/api/scores','POST',{'player_id':self.p['id'],'game_id':gid,'points':900},self.admin)[0],400)
        self.request('/api/games/'+str(gid),'PUT',{'name':'Reflex Rush · Normal','genre':'Reaction','max_score':1000000,'active':0},self.admin)
        self.assertEqual(self.request('/api/play/start','POST',{'mode':'normal'},self.p)[0],409)
        self.now+=1;r=self.start(mode='easy')
        self.request('/api/players/'+str(self.p['id']),'PUT',{'name':'Mohamed Moustafa','active':0},self.admin)
        self.assertEqual(self.store.query('SELECT status FROM rounds WHERE id=?',(r['id'],))[0]['status'],'cancelled')
        self.assertEqual(self.store.query('SELECT * FROM members WHERE user_id=?',(self.p['id'],)),[])

if __name__=='__main__':unittest.main(verbosity=2)
