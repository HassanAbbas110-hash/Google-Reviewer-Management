"""Offline, allowlisted code-only update. Run from the project folder."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

FILES={'reviewer/ai.py', 'Update-App.cmd', '.gitignore', 'reviewer/engine.py', 'tools/install_demo_update.py', 'tools/install_tone_safety_update.py', 'reviewer/__init__.py', 'reviewer/static/lab.js', 'reviewer/website.py', 'tools/install_quality_update.py', 'docs/superpowers/plans/2026-11-15-local-completion.md', 'reviewer/lab.py', 'reviewer/database.py', 'docs/BUILD_STATUS.md', 'README.md', 'tools/update_local.py', 'reviewer/cli.py', 'tests/test_integrations.py', 'Start.cmd', 'docs/superpowers/specs/2026-11-15-review-manager-design.md', 'reviewer/reports.py', 'reviewer/static/app.css', 'reviewer/templates/demo.html', 'docs/superpowers/plans/2026-11-15-review-manager.md', 'docs/TONE_SAFETY.md', 'reviewer/templates/lab.html', 'requirements.txt', 'reviewer/templates/extracted.html', 'tests/test_form_submission.py', 'reviewer/templates/dashboard.html', 'reviewer/templates/message.html', 'tests/test_core.py', 'tests/test_local_completion.py', 'tests/test_notifications.py', 'tests/test_lab.py', 'tests/test_app_update.py', 'docs/REPLY_QUALITY.md', 'reviewer/notifications.py', 'reviewer/__main__.py', 'tests/test_demo.py', 'tests/test_qwen_mode.py', 'tests/test_reply_quality.py', 'tools/install_qwen_update.py', 'reviewer/google.py', 'tests/test_reports.py', 'reviewer/demo.py', 'docs/PILOT_CHECKLIST.md', 'tests/test_application.py', 'Setup.cmd', 'docs/LOCAL_MODEL_COMPARISON.md', 'tests/test_demo_update.py', 'reviewer/web.py', 'tests/test_routing_and_tone.py', 'reviewer/core.py', 'reviewer/templates/report.html'}


def install(root,bundle):
    root=Path(root).resolve(); bundle=Path(bundle).resolve()
    if not (root/'reviewer/web.py').is_file() or not (root/'Start.cmd').is_file():
        raise ValueError('Put Update-App.cmd and the app-update folder beside Start.cmd before running the update.')
    manifest=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    if set(manifest)!=FILES: raise ValueError('Unexpected update contents. No changes made.')
    source={}
    for name in FILES:
        for candidate,base in [(root/name,root),(bundle/'payload'/name,bundle/'payload')]:
            if not candidate.resolve().is_relative_to(base.resolve()) or any(parent.is_symlink() for parent in [candidate,*candidate.parents] if parent!=base.parent):
                raise ValueError('Symlink or unsafe update path. No changes made.')
    if (root/'.update-backups').is_symlink():raise ValueError('Unsafe backup path.')
    for name,digest in manifest.items():
        content=(bundle/'payload'/name).read_bytes()
        if hashlib.sha256(content).hexdigest()!=digest: raise ValueError('Update file failed verification: '+name)
        if name.endswith('.py'): compile(content,name,'exec')
        source[name]=content
    originals={name:(root/name).read_bytes() if (root/name).exists() else None for name in FILES}
    backup=root/'.update-backups'/('local-'+str(time.time_ns()))
    for name,content in originals.items():
        if content is not None:
            target=backup/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(content)
    try:
        for name,content in source.items():
            target=root/name; target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(target.name+'.update-next'); temporary.write_bytes(content); temporary.replace(target)
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
        print('Local test lab and reply checks installed. Business data and publishing settings were not changed.')
        print('Original code backup: '+str(backup))
        print('Run Start.cmd, hard-refresh Chrome/Edge, and open Local test lab and run Quick check (8 cases).')
    except Exception as exc:
        print('Update could not complete: '+str(exc))
        return 1
    return 0


if __name__=='__main__': sys.exit(main())
