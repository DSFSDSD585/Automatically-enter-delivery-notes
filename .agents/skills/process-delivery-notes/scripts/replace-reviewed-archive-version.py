"""Apply explicitly reviewed image-version replacements; never touch ledgers or sources."""
import argparse, hashlib, json, os, shutil, tempfile
from pathlib import Path

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def inside(path, root):
    p, r = Path(path).resolve(), Path(root).resolve()
    if p == r or r not in p.parents:
        raise ValueError(f'Path outside expected root: {p}')
    return p

def check_hash(path, expected):
    if len(expected) != 64 or sha(path).lower() != expected.lower():
        raise ValueError(f'Hash changed: {path}')

def outside_business_roots(path, settings):
    p=Path(path).resolve()
    for key in ('pending_root','ledger_root','primary_archive_root','settlement_archive_root'):
        root=Path(settings[key]).resolve()
        if p==root or root in p.parents:raise ValueError('Audit and backup paths must be outside business roots')

def run(plan, execute=False):
    settings=plan['settings']
    backup_root=Path(plan['backup_root']).resolve()
    journal=Path(plan['journal']).resolve()
    outside_business_roots(backup_root,settings);outside_business_roots(journal,settings)
    if not journal.parent.is_dir():raise ValueError('Journal parent missing')
    if execute:
        backup_root.mkdir(parents=True,exist_ok=True)
        with journal.open('a',encoding='utf-8') as f:f.write(json.dumps({'event':'start'})+'\n')
    results=[]
    for item in plan['items']:
        if item.get('review_status')!='same_physical_note_verified' or not item.get('review_evidence'):
            raise ValueError('Explicit same-note visual review is required')
        source=inside(item['source_file'],settings['pending_root'])
        ledger=inside(item['ledger_file'],settings['ledger_root'])
        target=inside(item['target'],settings[item['target_root']])
        if item['target_root'] not in ('primary_archive_root','settlement_archive_root'):
            raise ValueError('Invalid target root')
        if target.suffix.lower() not in ('.jpg','.jpeg','.png') or not target.parent.is_dir():raise ValueError('Invalid image target')
        source_format='png' if source.suffix.lower()=='.png' else 'jpeg'
        target_format='png' if target.suffix.lower()=='.png' else 'jpeg'
        if source_format!=target_format:raise ValueError('Cross-format replacement requires separate reviewed migration; never rename image bytes')
        if source_format=='png':
            with source.open('rb') as f:
                if f.read(8)!=b'\x89PNG\r\n\x1a\n':raise ValueError('PNG extension does not match file signature')
        check_hash(source,item['source_sha256']);check_hash(ledger,item['ledger_sha256'])
        result={**item,'status':'ready'}
        if sha(target)==item['source_sha256'].lower():
            result['status']='already_current';results.append(result);continue
        check_hash(target,item['expected_old_sha256'])
        backup=inside(backup_root/item['expected_old_sha256'].lower()/target.name,backup_root)
        result['backup_file']=str(backup)
        if execute:
            backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.exists():
                with target.open('rb') as src, backup.open('xb') as dst:shutil.copyfileobj(src,dst)
            check_hash(backup,item['expected_old_sha256'])
            with journal.open('a',encoding='utf-8') as f:
                f.write(json.dumps({**result,'status':'backup_verified'},ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
            fd,tmp=tempfile.mkstemp(prefix='.reviewed-version-',suffix='.tmp',dir=target.parent)
            try:
                with os.fdopen(fd,'wb') as dst,source.open('rb') as src:
                    shutil.copyfileobj(src,dst);dst.flush();os.fsync(dst.fileno())
                check_hash(tmp,item['source_sha256']);check_hash(source,item['source_sha256'])
                check_hash(ledger,item['ledger_sha256']);check_hash(target,item['expected_old_sha256'])
                os.replace(tmp,target)
                check_hash(target,item['source_sha256'])
                result['status']='replaced_backup_verified'
                with journal.open('a',encoding='utf-8') as f:
                    f.write(json.dumps(result,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
            finally:
                if Path(tmp).exists():Path(tmp).unlink()
        results.append(result)
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('plan');p.add_argument('--execute',action='store_true');p.add_argument('--report',required=True)
    args=p.parse_args()
    report=Path(args.report).resolve()
    if not report.parent.is_dir() or report==Path(args.plan).resolve():raise ValueError('Invalid report path')
    data=json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
    outside_business_roots(report,data['settings'])
    if report==Path(data['journal']).resolve():raise ValueError('Report must not overwrite journal')
    results=run(data,args.execute)
    report.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'items':len(results),'replaced':sum(r['status']=='replaced_backup_verified' for r in results),'source_cleanup':False}))
