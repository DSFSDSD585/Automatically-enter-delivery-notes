"""Make the original standalone regression checks visible to unittest discovery."""
import subprocess
import sys
import unittest
from pathlib import Path


class LegacyWorkflowTests(unittest.TestCase):
    def check(self,name):
        result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name(name))],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_history_inventory(self):self.check('test-inventory-history.py')
    def test_reviewed_version(self):self.check('test-reviewed-version.py')
