"""Launcher regression tests for the Windows forbidden-port failure."""
import contextlib
import io
from unittest import TestCase
from unittest.mock import Mock,patch
import start

class LauncherTests(TestCase):
    def test_forbidden_and_busy_ports_fall_back_before_opening_browser(self):
        server=Mock();server.server_port=49327;server.serve_forever.side_effect=KeyboardInterrupt
        attempted=[]
        def bind(address,store):
            attempted.append(address[1])
            if address[1]!=0:raise PermissionError('Simulated Windows denied/busy port')
            return server
        with patch.object(start,'Store'),patch.object(start,'Server',side_effect=bind),patch.object(start.threading,'Timer') as timer,patch.object(start.webbrowser,'open') as browser,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(start.main(),0)
            self.assertEqual(attempted,[5050,8081,8765,0])
            timer.assert_called_once();timer.call_args.args[1]()
            browser.assert_called_once_with('http://127.0.0.1:49327')
            self.assertIn('49327',output.getvalue())
            server.server_close.assert_called_once()

    def test_all_ports_denied_does_not_open_broken_browser_url(self):
        with patch.object(start,'Store'),patch.object(start,'Server',side_effect=PermissionError('Denied')),patch.object(start.threading,'Timer') as timer,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(start.main(),1);timer.assert_not_called()
