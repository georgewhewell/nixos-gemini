"""Exercise real CLI and USB wait-loop timeout boundaries without USB access."""
import contextlib
import importlib.util
import io
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('reset_base', sys.argv.pop(1))
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
from mtkclient.Library.Port import Port
from mtkclient.Library import Port as port_module


class ConnectTimeout(unittest.TestCase):
    def port(self, deadline=120):
        port = Port.__new__(Port)
        port.config = SimpleNamespace(connect_deadline=deadline)
        port.cdc = SimpleNamespace(connected=False, connect=Mock(return_value=False))
        port.run_handshake = Mock(return_value=True)
        port.info = port.warning = port.debug = Mock()
        return port

    def test_cli_and_multi_preserve_one_deadline_until_connection(self):
        handler = Mock(); mtk = Mock(); mtk.config.debugmode = False
        handler.connect.return_value = handler.configure_da.return_value = mtk
        with patch.object(base.mtk_main.time, 'monotonic', return_value=10), \
                patch.object(base.mtk_main, 'Mtk', return_value=mtk) as ctor, \
                patch.object(base.mtk_main, 'DaHandler', return_value=handler), \
                patch.object(sys, 'argv', ['mtk', '--connect-timeout', '120', 'multi',
                                         'printgpt;reset --bootmode reboot --preserve-rtc']):
            base.cli.main()
        self.assertEqual(ctor.call_args.kwargs['config'].connect_deadline, 130)
        handler.connect.assert_called_once()
        self.assertTrue(handler.handle_da_cmds.call_args_list[-1].args[2].preserve_rtc)

    def test_cli_rejects_invalid_timeout_and_unsupported_serial(self):
        for argv in (['--connect-timeout', '0'], ['--connect-timeout', '-1'],
                     ['--connect-timeout', 'NaN'], ['--connect-timeout', '1.5'],
                     ['--connect-timeout', '120', '--serialport', '/dev/ttyUSB0']):
            with self.subTest(argv=argv), patch.object(base.cli, 'Main') as main, \
                    patch.object(sys, 'argv', ['mtk']+argv+['multi','printgpt']), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                base.cli.main()
            self.assertEqual(error.exception.code, 2)
            main.assert_not_called()

    def test_expired_scan_never_opens_device(self):
        p = self.port()
        with patch.object(port_module.time, 'monotonic', return_value=120), self.assertRaises(SystemExit) as error:
            p.handshake()
        self.assertEqual(error.exception.code, 124)
        p.cdc.connect.assert_not_called(); p.run_handshake.assert_not_called()

    def test_late_connection_can_finish_after_scan_deadline(self):
        p = self.port(); clock = [119.9]
        def connect():
            p.cdc.connected = True
            clock[0] = 121  # Opening the device crosses the old scan boundary.
            return True
        def handshake():
            self.assertIsNone(p.config.connect_deadline)
            clock[0] = 175
            return True
        p.cdc.connect.side_effect = connect
        p.run_handshake.side_effect = handshake
        with patch.object(port_module.time, 'monotonic', side_effect=lambda: clock[0]):
            self.assertTrue(p.handshake())
        self.assertEqual(clock[0],175)
        self.assertIsNone(p.config.connect_deadline)

    def test_failed_handshake_after_open_is_a_connected_session(self):
        p = self.port()
        def connect():
            p.cdc.connected = True
            return True
        p.cdc.connect.side_effect = connect; p.run_handshake.return_value = False
        with patch.object(port_module.time, 'monotonic', return_value=119.9), patch.object(port_module.time, 'sleep'):
            self.assertFalse(p.handshake())
        self.assertIsNone(p.config.connect_deadline)

    def test_retry_batches_do_not_restart_idle_deadline(self):
        p = self.port(deadline=1); clock = [0]
        with patch.object(port_module.time, 'monotonic', side_effect=lambda:clock[0]), \
                patch.object(port_module.time, 'sleep', side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            self.assertFalse(p.handshake(maxtries=2))
            self.assertEqual(p.config.connect_deadline,1)
            with self.assertRaises(SystemExit) as error: p.handshake(maxtries=2)
        self.assertEqual(error.exception.code,124)
        self.assertLess(clock[0],1.4)

    def test_default_wait_remains_unlimited(self):
        p = self.port(deadline=None)
        p.cdc.connect.side_effect = [False,True]
        with patch.object(port_module.time,'monotonic',return_value=999999), patch.object(port_module.time,'sleep'):
            self.assertTrue(p.handshake())
        self.assertEqual(p.cdc.connect.call_count,2)


if __name__ == '__main__': unittest.main()
