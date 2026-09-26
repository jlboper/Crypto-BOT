"""Build a deterministic allowlisted ZIP; signing is performed by the portal."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trader.update_manager import safe_name, MAX_PACKAGE, MAX_EXPANDED


def build(root, paths, output, commit, sequence, expires):
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('Exact commit required')
    files = {}
    for name in sorted(set(paths)):
        try:
            safe_name(name)
        except ValueError:
            continue
        path = root/name
        if path.suffix.lower() not in {'.py','.toml','.md','.ps1','.sh','.js','.mjs','.html','.css','.png','.ico','.webmanifest'}:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Linked release file')
        content = path.read_bytes()
        if name.endswith('.py'):
            compile(content, name, 'exec')
        files[name] = content
    version = tomllib.loads(files['pyproject.toml'].decode())['project']['version']
    bridge_release = version == '0.8.6'
    if bridge_release:
        files.pop('config.toml', None)
    if not {'trader/__main__.py','trader/runtime_control.py','pyproject.toml'} <= files.keys():
        raise ValueError('Incomplete supervised release')
    if len(files)>2000 or sum(map(len,files.values()))>MAX_EXPANDED:
        raise ValueError('Release size limit')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            entry = zipfile.ZipInfo(name, date_time=(2020,1,1,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED
            entry.external_attr=0o100644<<16
            archive.writestr(entry,content)
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or output.stat().st_size>MAX_PACKAGE:
        raise ValueError('Invalid release metadata')
    release_config = tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
    release_mode = 'paper' if bridge_release else str(release_config.get('bot', {}).get('mode', '')).lower()
    if release_mode not in {'paper', 'testnet'}:
        raise ValueError('Invalid release execution mode')
    manifest={'app':'crypto-ai-trading-bot','mode':release_mode,'version':version,'runtime_protocol':1,
              'commit':commit,'sequence':sequence,'expires':expires,'size':output.stat().st_size,
              'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
              'files':{name:hashlib.sha256(content).hexdigest() for name,content in files.items()},
              'package_url':f'https://raw.githubusercontent.com/jlboper/Crypto-BOT/bot-releases/packages/{commit}.zip'}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--commit',required=True)
    parser.add_argument('--sequence',type=int,required=True)
    parser.add_argument('--expires',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    value=build(root,filter(None,paths),args.output,args.commit,args.sequence,args.expires)
    print(json.dumps({'version':value['version'],'files':len(value['files']),'size':value['size']}))
