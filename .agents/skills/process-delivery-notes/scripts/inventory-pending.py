"""Read-only stable inventory with carrier-specific history candidates."""
import argparse,csv,hashlib,json,re
from collections import defaultdict
from pathlib import Path
from delivery_paths import pending_files, history_rows

def inventory(settings,history_root,mode="self_pickup"):
    history=defaultdict(list)
    for p,r in history_rows(history_root):
        h=(r.get('source_sha256') or '').lower()
        if not re.fullmatch('[a-f0-9]{64}',h) or not r.get('delivery_no'):continue
        history[h].append({k:r.get(k,'') for k in ('delivery_no','ledger_file','ledger_sheet','ledger_rows','primary_target','settlement_target')}|{'history_file':str(p)})
    rows=[];groups=defaultdict(list)
    files=pending_files(settings,mode)
    for i,p in enumerate(files,1):
        before=p.stat()
        with p.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
        after=p.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError(f'Source changed during inventory: {p}')
        row={'index':i,'source_file':str(p),'source_sha256':h,'size':after.st_size,'mtime_ns':after.st_mtime_ns}
        if h in history:row['historical_candidates']=history[h]
        rows.append(row);groups[h].append(str(p))
    return {'files':rows,'total_files':len(rows),'unique_sha256':len(groups),'historical_hash_candidates':sum(bool(r.get('historical_candidates')) for r in rows),'exact_duplicate_groups':[v for v in groups.values() if len(v)>1],'mode':mode,'status':('candidates_only_require_fresh_distribution_backup_and_archive_verification' if mode=='factory' else 'candidates_only_require_fresh_ledger_and_dual_archive_verification')}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--settings',default=str(Path(__file__).parent.parent/'assets/settings.json'));p.add_argument('--mode',choices=['self_pickup','factory'],default='self_pickup');p.add_argument('--history-root',required=True);p.add_argument('--report',required=True)
    a=p.parse_args();settings=json.loads(Path(a.settings).read_text(encoding='utf-8-sig'));out=Path(a.report).resolve()
    for key in ('pending_root','ledger_root','primary_archive_root','settlement_archive_root'):
        root=Path(settings[key]).resolve()
        if out==root or root in out.parents:raise ValueError('Inventory output must be outside business roots')
    if out.exists():raise FileExistsError('Preserve stable batch indexes: choose a new report filename instead of overwriting an existing inventory')
    result=inventory(settings,a.history_root,a.mode)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('files','exact_duplicate_groups')},ensure_ascii=False))
