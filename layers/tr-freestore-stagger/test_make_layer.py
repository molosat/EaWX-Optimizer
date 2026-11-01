"""python -I -B -m unittest discover -s layers/tr-freestore-stagger -p test_make_layer.py"""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import make_layer

SOURCE = b'function FreeStoreService()\r\nend\r\nUnitServiceRate = 40\r\n'


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tr = self.root / 'tr'
        (self.tr / make_layer.SCRIPT).parent.mkdir(parents=True)
        (self.tr / make_layer.SCRIPT).write_bytes(SOURCE)
        patch = mock.patch.object(make_layer, 'EXPECTED_SHA256', hashlib.sha256(SOURCE).hexdigest())
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_copy_keeps_tr_bytes_and_appends_the_wrapper(self):
        dst, _ = make_layer.build(self.tr, self.root / 'layer')
        out = dst.read_bytes()
        self.assertTrue(out.startswith(SOURCE))
        self.assertIn(b'StaggerPhase = slot * StaggerPeriod / StaggerSlots\r\n', out)
        self.assertEqual((self.tr / make_layer.SCRIPT).read_bytes(), SOURCE)

    def test_refuses_tr_folder_and_folders_inside_or_around_it(self):
        for out in (self.tr, self.tr / 'Data', self.root):
            with self.assertRaises(SystemExit):
                make_layer.build(self.tr, out)
        self.assertEqual((self.tr / make_layer.SCRIPT).read_bytes(), SOURCE)

    def test_refuses_a_hard_link_to_the_tr_script(self):
        dst = self.root / 'layer' / make_layer.SCRIPT
        dst.parent.mkdir(parents=True)
        os.link(self.tr / make_layer.SCRIPT, dst)
        with self.assertRaises(SystemExit):
            make_layer.build(self.tr, self.root / 'layer')
        self.assertEqual((self.tr / make_layer.SCRIPT).read_bytes(), SOURCE)

    def test_replacing_an_existing_file_never_writes_through_it(self):
        dst = self.root / 'layer' / make_layer.SCRIPT
        dst.parent.mkdir(parents=True)
        os.link(self.tr / make_layer.SCRIPT, dst)
        with mock.patch.object(make_layer, 'check_destination', return_value=dst):
            make_layer.build(self.tr, self.root / 'layer')
        self.assertEqual((self.tr / make_layer.SCRIPT).read_bytes(), SOURCE)
        self.assertIn(b'StaggerPhase', dst.read_bytes())

    def test_refuses_unexpected_script(self):
        (self.tr / make_layer.SCRIPT).write_bytes(SOURCE + b'-- changed\r\n')
        with self.assertRaises(SystemExit):
            make_layer.build(self.tr, self.root / 'layer')
        self.assertFalse((self.root / 'layer').exists())


if __name__ == '__main__':
    unittest.main()
