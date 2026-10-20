import ctypes as C
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rocomusic.device_input import DeviceAPI, KeyStroke
from rocomusic.native import InputError, SCAN


class DeviceTests(unittest.TestCase):
    def library(self):
        dll=Mock()
        dll.interception_create_context.return_value=123
        dll.interception_get_hardware_id.side_effect=lambda context,device,*args: 20 if device==2 else 0
        dll.interception_send.side_effect=lambda ctx,device,strokes,count: count
        return dll

    def test_send_batch_preserves_up_then_chord(self):
        dll=self.library()
        api=DeviceAPI(_dll=dll)
        seen=[]
        def send(ctx,device,strokes,count):
            seen.append((ctx,device,[(s.code,s.state,s.information) for s in strokes]))
            return count
        dll.interception_send.side_effect=send
        api.send(('F',),('F','J'))
        self.assertEqual(seen,[(123,2,[(SCAN['F'],1,0),(SCAN['F'],0,0),(SCAN['J'],0,0)])])
        self.assertEqual(C.sizeof(KeyStroke),8)
        self.assertNotIn('interception_set_filter',[call[0] for call in dll.method_calls])
        api.close()
        dll.interception_destroy_context.assert_called_once_with(123)

    def test_missing_driver_never_sends(self):
        dll=self.library();dll.interception_create_context.return_value=None
        api=DeviceAPI(_dll=dll)
        with self.assertRaisesRegex(InputError,'驱动未就绪'): api.send((),('F',))
        dll.interception_send.assert_not_called()

    def test_no_keyboard_destroys_context(self):
        dll=self.library();dll.interception_get_hardware_id.side_effect=None;dll.interception_get_hardware_id.return_value=0
        api=DeviceAPI(_dll=dll)
        with self.assertRaisesRegex(InputError,'没有可用键盘'): api.ensure_ready()
        self.assertIsNone(api.context)
        dll.interception_destroy_context.assert_called_once_with(123)

    def test_partial_output_is_error_without_replay(self):
        dll=self.library();dll.interception_send.side_effect=None;dll.interception_send.return_value=1
        api=DeviceAPI(_dll=dll)
        with self.assertRaises(InputError): api.send((),('F','J'))
        self.assertEqual(dll.interception_send.call_count,1)
        api.close()
