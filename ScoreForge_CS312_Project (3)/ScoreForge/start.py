"""Convenient local launcher; opens the browser only after binding succeeds."""
import sys
if sys.version_info < (3,10):
    raise SystemExit('ScoreForge requires Python 3.10 or newer.')
import threading
import webbrowser
from server import ROOT, Server, Store

def main():
    store=Store(ROOT/'data'/'scoreforge.db')
    server=None
    for port in (5050,8081,8765,0):
        try:
            server=Server(('127.0.0.1',port),store)
            break
        except OSError:
            continue
    if server is None:
        print('Could not open a local port. Check whether security software blocks Python.')
        return 1
    url=f'http://127.0.0.1:{server.server_port}'
    print('\nScoreForge | '+url)
    print('Admin: admin / Admin@12345 (unless changed)')
    print('Player: player1 / Player@12345 (unless changed)')
    print('Keep this window open. Press Ctrl+C to stop.\n',flush=True)
    threading.Timer(0.7,lambda:webbrowser.open(url)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:print('\nScoreForge stopped.')
    finally:server.server_close()
    return 0
if __name__=='__main__':sys.exit(main())
