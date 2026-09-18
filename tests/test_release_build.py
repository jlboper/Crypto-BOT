import tempfile
import unittest
import zipfile
from pathlib import Path
from scripts.build_bot_release import build

class ReleaseBuildTests(unittest.TestCase):
    def test_deterministic_archive_excludes_credentials_data_and_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            files={'trader/__main__.py':'# fixture\n','trader/runtime_control.py':'# fixture\n',
                   'pyproject.toml':'[project]\nversion="0.6.3"\n','.env.local':'secret fixture',
                   'config.toml':'protected','data/database.db':'private fixture',
                   'trader/__pycache__/secret.pyc':'cache'}
            for name,content in files.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
            first=build(root,files.keys(),root/'first.zip','a'*40,12345,1800000000)
            second=build(root,files.keys(),root/'second.zip','a'*40,12345,1800000000)
            self.assertEqual(first,second)
            with zipfile.ZipFile(root/'first.zip') as archive:
                self.assertEqual(set(archive.namelist()),{'trader/__main__.py','trader/runtime_control.py','pyproject.toml'})
            self.assertEqual(first['runtime_protocol'],1)
