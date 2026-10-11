import importlib.util,tempfile,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('version',Path(__file__).with_name('replace-reviewed-archive-version.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory(prefix='delivery-version-test-') as tmp:
    r=Path(tmp)
    for d in ['pending','ledger','primary','settlement','backup']:(r/d).mkdir()
    s=r/'pending/new.jpg';s.write_bytes(b'new-image')
    l=r/'ledger/book.xlsx';l.write_bytes(b'saved-test-ledger')
    t=r/'primary/test.jpg';t.write_bytes(b'old-image')
    item={'source_file':str(s),'source_sha256':m.sha(s),'ledger_file':str(l),'ledger_sha256':m.sha(l),'target':str(t),'target_root':'primary_archive_root','expected_old_sha256':m.sha(t),'review_status':'same_physical_note_verified','review_evidence':'synthetic test'}
    plan={'settings':{'pending_root':str(r/'pending'),'ledger_root':str(r/'ledger'),'primary_archive_root':str(r/'primary'),'settlement_archive_root':str(r/'settlement')},'backup_root':str(r/'backup'),'journal':str(r/'journal.jsonl'),'items':[item]}
    assert m.run(plan)[0]['status']=='ready' and t.read_bytes()==b'old-image'
    out=m.run(plan,True)[0]
    assert out['status']=='replaced_backup_verified' and t.read_bytes()==s.read_bytes()
    assert Path(out['backup_file']).read_bytes()==b'old-image' and s.exists()
    assert m.run(plan,True)[0]['status']=='already_current'
    l.write_bytes(b'changed')
    try:m.run(plan,True)
    except ValueError:pass
    else:raise AssertionError('Changed ledger not blocked')
    l.write_bytes(b'saved-test-ledger');t.write_bytes(b'unreviewed-change')
    try:m.run(plan,True)
    except ValueError:pass
    else:raise AssertionError('Changed target not blocked')
    assert t.read_bytes()==b'unreviewed-change' and s.exists()
    png=r/'pending/new.png';png.write_bytes(b'\x89PNG\r\n\x1a\nnew')
    pngtarget=r/'primary/test.png';pngtarget.write_bytes(b'\x89PNG\r\n\x1a\nold')
    pngitem={**item,'source_file':str(png),'source_sha256':m.sha(png),'target':str(pngtarget),'expected_old_sha256':m.sha(pngtarget)}
    pngplan={**plan,'items':[pngitem]}
    assert m.run(pngplan,True)[0]['status']=='replaced_backup_verified'
    assert pngtarget.read_bytes()==png.read_bytes() and png.exists()
    try:m.run({**plan,'items':[{**pngitem,'target':str(t)}]},True)
    except ValueError:pass
    else:raise AssertionError('Cross-format bytes replacement not blocked')
print('Version recovery tests passed: dry run, backup, replacement, replay, changed ledger, changed target')
