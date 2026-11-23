"""Exercise the desktop launcher and shared capacity through two HTTP processes."""
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]

def request(url, path, method='GET', body=None, session=None):
    conn = http.client.HTTPConnection('127.0.0.1', urlparse(url).port, timeout=20)
    headers = {'Content-Type': 'application/json'}
    if session:
        headers.update(Cookie=session[0], **{'X-CSRF-Token': session[1]})
    conn.request(method, path, json.dumps(body) if body is not None else None, headers)
    response = conn.getresponse()
    status, cookie = response.status, response.getheader('Set-Cookie')
    data = json.loads(response.read())
    conn.close()
    return status, data, cookie

def login(url, username, password):
    status, data, cookie = request(url, '/api/login', 'POST', dict(username=username, password=password))
    assert status == 200, data
    return cookie.split(';')[0], data['csrf']

def main():
    processes = []
    with tempfile.TemporaryDirectory() as directory:
        try:
            urls = []
            for _ in range(2):
                process = subprocess.Popen([sys.executable, '-u', str(ROOT/'desktop_host.py')],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                    env={**os.environ, 'SCOREFORGE_DATA_DIR': directory})
                processes.append(process)
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    line = pool.submit(process.stdout.readline).result(timeout=30)
                assert line.startswith('READY http://127.0.0.1:'), line
                urls.append(line.strip()[6:])
            assert urls[0] != urls[1], urls
            admins = [login(url, 'admin', 'Admin@12345') for url in urls]
            status, setup, _ = request(urls[0], '/api/demo/start', 'POST', {}, admins[0])
            assert status == 201, setup
            def join(index):
                host = index % 2
                return request(urls[host], '/api/demo/join', 'POST',
                    dict(room_id=setup['room_id'], player_id=setup['players'][index]), admins[host])[0]
            with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
                statuses = list(pool.map(join, range(7)))
            assert statuses.count(200) == 3 and statuses.count(409) == 4, statuses
            for url, admin in zip(urls, admins):
                _, data, _ = request(url, '/api/demo/state', session=admin)
                room = next(r for r in data['rooms'] if r['id'] == setup['room_id'])
                assert room['occupied'] == 4, room
            player = login(urls[0], 'player1', 'Player@12345')
            status, data, _ = request(urls[0], '/api/play/start', 'POST', {'mode':'normal'}, player)
            assert status == 200 and data['round']['status'] == 'active', data
            status, data, _ = request(urls[0], '/api/play/cancel', 'POST', {}, player)
            assert status == 200, data
            print('PASS: desktop launcher, port fallback, shared database, two-process HTTP concurrency (3 accepted / 4 rejected), gameplay start/cancel.')
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()

if __name__ == '__main__':
    main()
