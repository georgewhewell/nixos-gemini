#!/usr/bin/env python3
"""Keep deployment validation tied to ALSA's effective hardware parameters.

The fixture follows the two Props records in a real onboard pw-dump: the
adapter reports logical volume channels, and ALSA reports its hardware order
in the alternating key/value params array. Metadata alone cannot pass.
"""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'audio_evidence', Path(__file__).with_name('audio-playback-evidence.py'))
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


def sink(order='[ FR, FL ]', use_chmap=False):
    return dict(id=55, type='PipeWire:Interface:Node', info=dict(
        state='suspended', props={
            'media.class': 'Audio/Sink',
            'node.name': 'alsa_output.platform-sound.HiFi__Speaker__sink',
            'api.alsa.path': 'hw:mt6797mt6351,0',
            'audio.channels': 2, 'audio.position': '["FR", "FL"]',
            'device.profile.name': 'HiFi: Speaker: sink',
        }, params={'Props': [
            {'channelMap': ['FL', 'FR'], 'params': ['channelmix.disable', False]},
            {'device': 'hw:mt6797mt6351,0', 'params': [
                'audio.channels', 2, 'audio.position', order,
                'api.alsa.use-chmap', use_chmap]},
        ]}))


class HardwareMapping(unittest.TestCase):
    def inspect(self, objects, passes=True):
        output = io.StringIO()
        with patch.object(audio.subprocess, 'run', return_value=SimpleNamespace(
                stdout=json.dumps(objects))), contextlib.redirect_stdout(output):
            if passes:
                audio.inspect()
            else:
                with self.assertRaises(RuntimeError):
                    audio.inspect()
        return json.loads(output.getvalue())

    def test_suspended_sink_has_separate_client_and_hardware_maps(self):
        result = self.inspect([sink()])['sinks'][0]
        self.assertEqual(result['channel_maps'], [['FL', 'FR']])
        self.assertEqual(result['hardware_positions'], [['FR', 'FL']])

    def test_hardware_position_encodings(self):
        for position in ('[ FR, FL ]', '["FR", "FL"]', ['FR', 'FL']):
            with self.subTest(position=position):
                self.inspect([sink(position)])

    def test_native_headphone_profile(self):
        obj = sink()
        obj['info']['props']['device.profile.name'] = 'HiFi: Headphones: sink'
        self.inspect([obj])

    def test_metadata_alone_cannot_prove_hardware_order(self):
        self.inspect([sink('[ FL, FR ]')], passes=False)

    def test_hardware_chmap_cannot_override_correction(self):
        self.inspect([sink(use_chmap=True)], passes=False)

    def test_missing_hardware_parameters(self):
        obj = sink()
        obj['info']['params']['Props'].pop()
        self.inspect([obj], passes=False)

    def test_reversed_client_map_would_double_correct(self):
        obj = sink()
        obj['info']['params']['Props'][0]['channelMap'] = ['FR', 'FL']
        self.inspect([obj], passes=False)

    def test_missing_onboard_sink(self):
        self.inspect([], passes=False)

    def test_other_devices_and_capture_are_ignored(self):
        external = copy.deepcopy(sink())
        external['info']['props']['node.name'] = 'unrelated-output'
        capture = copy.deepcopy(sink())
        capture['info']['props']['media.class'] = 'Audio/Source'
        result = self.inspect([external, capture, sink()])
        self.assertEqual(len(result['sinks']), 1)


if __name__ == '__main__':
    unittest.main()
