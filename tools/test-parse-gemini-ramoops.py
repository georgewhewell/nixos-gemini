"""Ramoops ring chronology, extent and integrity rejection tests."""
import importlib.util
from pathlib import Path
import struct
import unittest

s=importlib.util.spec_from_file_location('r',Path(__file__).with_name('parse-gemini-ramoops.py'))
r=importlib.util.module_from_spec(s);s.loader.exec_module(r)

class Rings(unittest.TestCase):
    def test_empty_partial_full_and_wrapped(self):
        for start,size,data,expected in ((0,0,b'xxxx',b''),(2,2,b'abxx',b'ab'),
                                         (0,4,b'abcd',b'abcd'),(2,4,b'cdab',b'abcd')):
            blob=struct.pack('<III',r.SIGNATURE,start,size)+data
            self.assertEqual(r.ring(blob,0,16),expected)
    def test_invalid_header_or_extent(self):
        good=struct.pack('<III',r.SIGNATURE,2,4)+b'cdab'
        for blob,offset,extent in ((good,-1,16),(good,0,17),(good,0,11),
              (struct.pack('<III',0,2,4)+b'cdab',0,16),
              (struct.pack('<III',r.SIGNATURE,5,4)+b'cdab',0,16),
              (struct.pack('<III',r.SIGNATURE,2,5)+b'cdab',0,16)):
            with self.assertRaises(ValueError):r.ring(blob,offset,extent)

if __name__=='__main__':unittest.main()
