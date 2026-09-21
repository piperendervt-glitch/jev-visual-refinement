"""Explicit expired fixture-run purge; no traversal of other runs or user media."""
import json
from pathlib import Path
import sqlite3
import time
from contextlib import closing


def purge_run(directory,allowed_root,now=None):
    root=Path(allowed_root).resolve();target=Path(directory).absolute()
    if any(p.is_symlink() or p.is_junction() for p in (target,*target.parents)):raise ValueError('reparse_denied')
    target=target.resolve()
    if target.parent!=root:raise ValueError('run_scope')
    dbpath=target/'state.sqlite'
    with closing(sqlite3.connect(f'file:{dbpath.as_posix()}?mode=ro',uri=True)) as db:
        if (time.time() if now is None else now)<float(db.execute("SELECT value FROM meta WHERE key='expires'").fetchone()[0]):raise ValueError('retention_not_expired')
    expected={dbpath,Path(str(dbpath)+'-journal')}
    files=set(target.iterdir())
    if not files<=expected:raise ValueError('unlisted_payload_or_export')
    for path in files:
        if path.is_symlink() or path.is_junction() or not path.is_file():raise ValueError('unexpected_path')
    removed=[]
    for path in files:path.unlink();removed.append(path.name)
    target.rmdir()
    return dict(removed=removed,physical_device_secure_erase=False)
