"""Offline, allowlisted code-only update. Run from the project folder."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

FILES={'reviewer/web.py','reviewer/demo.py','reviewer/templates/dashboard.html','reviewer/templates/demo.html','reviewer/static/app.css'}


def install(root,bundle):
    root=Path(root).resolve(); bundle=Path(bundle).resolve()
    if not (root/'reviewer/web.py').is_file() or not (root/'Start.cmd').is_file():
        raise ValueError('Put Update-Demo.cmd and the demo-update folder beside Start.cmd before running the update.')
    manifest=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    if set(manifest)!=FILES: raise ValueError('Unexpected update contents. No changes made.')
    source={}
    for name,digest in manifest.items():
        content=(bundle/'payload'/name).read_bytes()
        if hashlib.sha256(content).hexdigest()!=digest: raise ValueError('Update file failed verification: '+name)
        if name.endswith('.py'): compile(content,name,'exec')
        source[name]=content
    originals={name:(root/name).read_bytes() if (root/name).exists() else None for name in FILES}
    backup=root/'.update-backups'/('demo-'+str(time.time_ns()))
    for name,content in originals.items():
        if content is not None:
            target=backup/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(content)
    try:
        for name,content in source.items():
            target=root/name; target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(target.name+'.demo-next'); temporary.write_bytes(content); temporary.replace(target)
    except Exception:
        for name,content in originals.items():
            target=root/name
            if content is None: target.unlink(missing_ok=True)
            else: target.write_bytes(content)
        raise
    return backup


def main():
    root=Path.cwd(); bundle=Path(__file__).resolve().parent
    try:
        sys.path.insert(0,str(root))
        from reviewer.cli import InstanceLock
        data=root/'data'; data.mkdir(exist_ok=True)
        with InstanceLock(data/'app.lock'):
            backup=install(root,bundle)
        print('Demo update installed. Business data and publishing settings were not changed.')
        print('Original code backup: '+str(backup))
        print('Run Start.cmd, press Ctrl+Shift+R, open your business and click Test local AI.')
    except Exception as exc:
        print('Update could not complete: '+str(exc))
        return 1
    return 0


if __name__=='__main__': sys.exit(main())
