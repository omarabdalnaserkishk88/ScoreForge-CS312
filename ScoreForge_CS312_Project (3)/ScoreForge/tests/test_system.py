"""Real HTTP integration tests. Run: python -m unittest discover -s tests -v"""
import concurrent.futures
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Server, Store

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); cls.db=Path(cls.tmp.name)/'test.db'
        cls.store=Store(cls.db); cls.server=Server(('127.0.0.1',0),cls.store)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.admin=cls.login('admin','Admin@12345');cls.player=cls.login('player1','Player@12345')

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.tmp.cleanup()

    @classmethod
    def request(cls,path,method='GET',data=None,session=None,csrf=True,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',cls.server.server_port,timeout=20)
        h={'Content-Type':'application/json'}
        if session:
            h['Cookie']=session['cookie']
            if csrf:h['X-CSRF-Token']=session['csrf']
        h.update(headers or {})
        connection.request(method,path,None if data is None else json.dumps(data),h)
        r=connection.getresponse();body=r.read();status=r.status;cookie=r.getheader('Set-Cookie');typ=r.getheader('Content-Type','');connection.close()
        return status,json.loads(body) if 'application/json' in typ else body,cookie

    @classmethod
    def login(cls,username,password):
        status,data,cookie=cls.request('/api/login','POST',{'username':username,'password':password})
        assert status==200,(status,data)
        return {'cookie':cookie.split(';')[0],'csrf':data['csrf'],'id':data['user']['id']}

    def test_01_anonymous_and_role_permissions(self):
        self.assertEqual(self.request('/api/players')[0],401)
        self.assertEqual(self.request('/api/audit',session=self.player)[0],403)
        self.assertEqual(self.request('/api/scores','POST',{},self.player)[0],403)
        self.assertEqual(self.request('/api/demo/start','POST',{},self.player)[0],403)
        self.assertEqual(self.request('/api/rooms/join','POST',{'room_id':1},self.admin)[0],403)

    def test_02_csrf_and_origin(self):
        self.assertEqual(self.request('/api/players','POST',{},self.admin,False)[0],403)
        self.assertEqual(self.request('/api/players','POST',{},self.admin,headers={'Origin':'http://evil.invalid'})[0],403)

    def test_03_get_player_and_no_password_leak(self):
        status,data,_=self.request('/api/players/2',session=self.player)
        self.assertEqual(status,200);self.assertEqual(data['player']['name'],'Mohamed Moustafa')
        status,data,_=self.request('/api/players',session=self.admin)
        self.assertNotIn('password',json.dumps(data));self.assertEqual(len(data['players']),4)
        status,data,_=self.request('/api/scores',session=self.player)
        self.assertTrue(all(s['player_id']==2 for s in data['scores']))

    def test_04_crud_validation_and_persistence(self):
        status,data,_=self.request('/api/players','POST',{'name':'Test Player','username':'test-player','password':'StrongPass123'},self.admin)
        self.assertEqual(status,201);pid=data['id']
        self.assertEqual(self.request('/api/players','POST',{'name':'Again','username':'test-player','password':'StrongPass123'},self.admin)[0],409)
        status,data,_=self.request('/api/games','POST',{'name':'Test Game','genre':'Test','max_score':100},self.admin)
        self.assertEqual(status,201);gid=data['id']
        self.assertEqual(self.request('/api/scores','POST',{'player_id':pid,'game_id':gid,'points':101},self.admin)[0],400)
        self.assertEqual(self.request('/api/scores','POST',{'player_id':pid,'game_id':gid,'points':True},self.admin)[0],400)
        status,data,_=self.request('/api/scores','POST',{'player_id':pid,'game_id':gid,'points':90,'note':'=1+1'},self.admin)
        self.assertEqual(status,201);sid=data['id']
        reopened=Store(self.db)
        self.assertEqual(reopened.query('SELECT points FROM scores WHERE id=?',(sid,))[0]['points'],90)
        self.assertEqual(self.request('/api/games/'+str(gid),'DELETE',{},self.admin)[0],409)
        self.assertEqual(self.request('/api/games/'+str(gid),'PUT',{'name':'Test Game','genre':'Test','max_score':50},self.admin)[0],400)
        status,export,_=self.request('/api/export',session=self.admin)
        self.assertEqual(status,200);self.assertIn(b"'=1+1",export)
        self.assertEqual(self.request('/api/scores/'+str(sid),'PUT',{'player_id':pid,'game_id':gid,'points':80},self.admin)[0],200)
        self.assertEqual(self.request('/api/scores/'+str(sid),'DELETE',{},self.admin)[0],200)
        self.assertEqual(self.request('/api/games/'+str(gid),'DELETE',{},self.admin)[0],200)
        self.assertEqual(self.request('/api/players/'+str(pid),'DELETE',{},self.admin)[0],200)

    def race(self,count):
        status,setup,_=self.request('/api/demo/start','POST',{},self.admin);self.assertEqual(status,201)
        gate=threading.Barrier(count)
        def join(pid):
            gate.wait(timeout=10)
            return self.request('/api/demo/join','POST',{'room_id':setup['room_id'],'player_id':pid},self.admin)[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool: statuses=list(pool.map(join,setup['players'][:count]))
        self.assertEqual(statuses.count(200),3);self.assertEqual(statuses.count(409),count-3)
        _,data,_=self.request('/api/demo/state',session=self.admin)
        room=data['rooms'][0];self.assertEqual(room['occupied'],4);self.assertEqual(len(set(x['id'] for x in room['members'])),4)
        return setup

    def test_05_three_simultaneous_applicants(self):self.race(3)
    def test_06_seven_simultaneous_applicants_repeated(self):
        for _ in range(10):self.race(7)

    def test_07_repeated_join_is_idempotent(self):
        _,setup,_=self.request('/api/demo/start','POST',{},self.admin)
        pid=setup['players'][0];body={'room_id':setup['room_id'],'player_id':pid}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.request('/api/demo/join','POST',body,self.admin),range(8)))
        self.assertTrue(all(x[0]==200 for x in results));self.assertEqual(sum(not x[1]['already_joined'] for x in results),1)
        _,data,_=self.request('/api/demo/state',session=self.admin);self.assertEqual(data['rooms'][0]['occupied'],2)

    def test_08_live_join_leave_reset(self):
        self.assertEqual(self.request('/api/rooms/join','POST',{'room_id':1},self.player)[0],200)
        self.assertEqual(self.request('/api/rooms/join','POST',{'room_id':1},self.player)[1]['already_joined'],True)
        self.assertEqual(self.request('/api/rooms/leave','POST',{'room_id':1},self.player)[0],200)
        self.assertEqual(self.request('/api/rooms/join','POST',{'room_id':1},self.player)[0],200)
        self.assertEqual(self.request('/api/rooms/reset','POST',{'room_id':1},self.admin)[0],200)
        self.assertEqual(self.request('/api/rooms',session=self.player)[1]['rooms'][0]['occupied'],0)

    def test_09_ties_have_competition_ranks(self):
        status,data,_=self.request('/api/scores','POST',{'player_id':3,'game_id':1,'points':8450},self.admin)
        self.assertEqual(status,201)
        _,rows,_=self.request('/api/leaderboard',session=self.player)
        ranks=[r['rank'] for r in rows['leaderboard'] if r['game_id']==1]
        self.assertEqual(ranks,[1,1,3,4])
        self.request('/api/scores/'+str(data['id']),'DELETE',{},self.admin)

    def test_10_disabling_revokes_session_and_seat(self):
        status,data,_=self.request('/api/players','POST',{'name':'Disable Test','username':'disable-test','password':'Player@12345'},self.admin)
        pid=data['id'];session=self.login('disable-test','Player@12345')
        self.request('/api/rooms/join','POST',{'room_id':1},session)
        self.assertEqual(self.request('/api/players/'+str(pid),'PUT',{'name':'Disable Test','active':0},self.admin)[0],200)
        self.assertEqual(self.request('/api/me',session=session)[0],401)
        self.assertEqual(self.store.query('SELECT * FROM members WHERE user_id=?',(pid,)),[])

    def test_11_database_capacity_guard(self):
        setup=self.race(7)
        unused=[r['id'] for r in self.store.query('SELECT id FROM users WHERE demo=1 AND id NOT IN (SELECT user_id FROM members WHERE room_id=?)',(setup['room_id'],))][0]
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.transaction() as db:db.execute('INSERT INTO members VALUES(?,?,0)',(setup['room_id'],unused))

    def test_12_password_change_and_logout(self):
        status,data,_=self.request('/api/players','POST',{'name':'Password Test','username':'password-test','password':'Player@12345'},self.admin)
        s1=self.login('password-test','Player@12345');s2=self.login('password-test','Player@12345')
        self.assertEqual(self.request('/api/password','POST',{'current':'Player@12345','password':'Different@12345'},s1)[0],200)
        self.assertEqual(self.request('/api/me',session=s2)[0],401)
        self.assertEqual(self.request('/api/me',session=s1)[0],200)
        self.assertEqual(self.request('/api/login','POST',{'username':'password-test','password':'Player@12345'})[0],401)
        self.assertEqual(self.request('/api/logout','POST',{},s1)[0],200)
        self.assertEqual(self.request('/api/me',session=s1)[0],401)

    def test_13_http_input_and_static_security(self):
        self.assertEqual(self.request('/api/games','POST',[],self.admin)[0],400)
        self.assertEqual(self.request('/../server.py')[0],404)
        self.assertEqual(self.request('/api/players/nope',session=self.admin)[0],400)
        self.assertEqual(self.request('/admin')[0],200) # shell has no privileged data
        self.assertEqual(self.request('/api/audit')[0],401)

if __name__=='__main__':unittest.main(verbosity=2)
