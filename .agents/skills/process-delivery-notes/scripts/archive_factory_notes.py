"""Verify saved factory notes and archive originals. Dry run unless --execute."""
import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

NS = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def workbook(path):
    """Read cached cells without launching Excel or assuming sheet numbering."""
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read('xl/workbook.xml'))
        rels = {e.attrib['Id']:e.attrib['Target'] for e in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(t.text or '' for t in e.findall('.//m:t',NS)) for e in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        sheets = {}
        for sheet in doc.find('m:sheets',NS):
            target = rels[sheet.attrib[REL]]
            target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            if target not in z.namelist(): continue
            rows = {}
            for row in ET.fromstring(z.read(target)).findall('.//m:sheetData/m:row',NS):
                values = {}
                for c in row.findall('m:c',NS):
                    address = c.attrib['r']; col = re.sub(r'\d','',address)
                    v = c.find('m:v',NS); value = v.text if v is not None else None
                    kind = c.get('t')
                    if kind == 's' and value is not None: value = strings[int(value)]
                    elif kind == 'inlineStr': value = ''.join(t.text or '' for t in c.findall('.//m:t',NS))
                    elif value is not None and kind not in ('str','e'):
                        value = Decimal(value)
                    if value is not None: values[col] = value
                rows[int(row.attrib['r'])] = values
            sheets[sheet.attrib['name']] = rows
        props = doc.find('m:workbookPr',NS)
        epoch = datetime(1904,1,1) if props is not None and props.get('date1904') in ('1','true') else datetime(1899,12,30)
        return sheets, epoch


def equal(a, b):
    if isinstance(a,Decimal) or isinstance(b,(int,float,Decimal)):
        try: return Decimal(str(a)) == Decimal(str(b))
        except Exception: return False
    return a == b


def leaf(value):
    if not isinstance(value,str) or not value or value.strip() != value or value in ('.','..') or re.search(r'[<>:"/\\|?*\x00-\x1f]',value) or value.endswith('.'):
        raise ValueError('Invalid filename/project component')
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM\d|LPT\d)(\..*)?',value):
        raise ValueError('Reserved filename')
    return value


def verify(item, settings):
    pending = Path(settings['factory_pending_root']).resolve()
    archive = Path(settings['settlement_archive_root']).resolve()
    source, backup, ledger = (Path(item[n]).resolve() for n in ('source_file','backup_file','ledger_file'))
    if not source.is_relative_to(pending) or source == pending: raise ValueError('Source outside factory pending root')
    if ledger != Path(settings['distribution_ledger']).resolve(): raise ValueError('Unexpected distribution workbook')
    if backup == source or backup.is_relative_to(pending) or backup.is_relative_to(archive): raise ValueError('Backup must be separate from business images')
    for field in ('source_sha256','backup_sha256','ledger_sha256'):
        if not re.fullmatch('[a-fA-F0-9]{64}',item.get(field,'')): raise ValueError('Missing reviewed hash: '+field)
    image_hash = item['source_sha256'].lower()
    if digest(backup) != image_hash or item['backup_sha256'].lower() != image_hash: raise ValueError('Backup hash mismatch')
    if source.exists() and digest(source) != image_hash: raise ValueError('Source changed')
    if digest(ledger) != item['ledger_sha256'].lower(): raise ValueError('Ledger changed; reverify')
    if (ledger.parent/('~$'+ledger.name)).exists(): raise ValueError('Target Excel lock present')
    note = leaf(item['delivery_no']); folder = leaf(item['archive_project'])
    arrival = date.fromisoformat(item['arrival_date'])
    if arrival.isoformat() != item['arrival_date']: raise ValueError('Arrival must be ISO date')
    project = (archive/folder).resolve()
    if not project.is_relative_to(archive) or not project.is_dir(): raise ValueError('Confirmed project directory missing')
    extension = source.suffix.lower()
    with backup.open('rb') as f: header = f.read(8)
    if extension == '.png' and header != b'\x89PNG\r\n\x1a\n': raise ValueError('Invalid PNG signature')
    if extension in ('.jpg','.jpeg') and not header.startswith(b'\xff\xd8\xff'): raise ValueError('Invalid JPEG signature')
    if extension not in ('.jpg','.jpeg','.png'): raise ValueError('Unsupported original image format')
    extension = '.jpg' if extension == '.jpeg' else extension
    target = (project/str(arrival.year)/(arrival.strftime('%m%d')+'已录'+note+extension)).resolve()
    if not target.is_relative_to(project): raise ValueError('Target outside project')
    for suffix in ('.jpg','.jpeg','.png'):
        other = target.with_suffix(suffix)
        if other != target and other.exists(): raise ValueError('Cross-format archive conflict')
    if target.exists() and digest(target) != image_hash: raise ValueError('Different image occupies target')
    if not source.exists() and not target.exists(): raise ValueError('Source absent and archive incomplete')
    sheets, epoch = workbook(ledger)
    if item.get('ledger_sheet') != '总览表': raise ValueError('Unexpected overview sheet')
    overview, stock = sheets['总览表'], sheets['入库信息表']
    by_stock = {}
    for r in stock.values():
        sid = r.get('A')
        if not isinstance(sid,str) or not sid.startswith('A-'): continue
        if sid in by_stock: raise ValueError('Duplicate inbound identifier')
        by_stock[sid] = r
    rows = item.get('expected_rows',[])
    if not rows or len({r['row'] for r in rows}) != len(rows): raise ValueError('Missing/duplicate expected detail rows')
    actual = {n for n,r in overview.items() if r.get('T') == note}
    if actual != {r['row'] for r in rows}: raise ValueError('Saved note detail set incomplete or changed')
    for expected in rows:
        cells = expected['cells']; saved = overview[expected['row']]
        if not set(('A','C','K','Q','R','S','T')) <= set(cells): raise ValueError('Required expected cells missing')
        for col,val in cells.items():
            if not equal(saved.get(col),val): raise ValueError('Saved cell mismatch: '+col+str(expected['row']))
        if saved['T'] != note or saved['K'] != item['project']: raise ValueError('Saved note/project differs')
        if (epoch+timedelta(days=float(saved['S']))).date() != arrival: raise ValueError('Saved arrival differs')
        if Decimal(str(saved['Q'])) <= 0 or Decimal(str(saved['R'])) <= 0 or Decimal(str(saved['R'])) % 1: raise ValueError('Invalid saved quantity')
        inbound = by_stock.get(saved['A'])
        if not inbound or inbound.get('N') != '厂发': raise ValueError('Not a factory inbound lot')
        for dest,src in {'C':'C','D':'E','E':'F','F':'G','G':'H','H':'I','J':'D','K':'M'}.items():
            if saved.get(dest) is None or not equal(saved.get(dest),inbound.get(src)): raise ValueError('Overview/inbound mismatch: '+dest)
    if digest(ledger) != item['ledger_sha256'].lower(): raise ValueError('Ledger changed during verification')
    return source,backup,ledger,target,image_hash


def run(manifest, settings, report, execute=False):
    report = Path(report).resolve()
    if report.exists() or Path(str(report)+'.journal.jsonl').exists(): raise FileExistsError('Use a new result path')
    for root_name in ('pending_root','ledger_root','primary_archive_root','settlement_archive_root','factory_pending_root'):
        if report.is_relative_to(Path(settings[root_name]).resolve()): raise ValueError('Result must be outside business roots')
    items = manifest.get('items',[])
    if not items: raise ValueError('Empty manifest')
    for field in ('source_file','delivery_no'):
        if len({str(i.get(field,'')) for i in items}) != len(items): raise ValueError('Duplicate '+field)
    results = []
    for item in items:
        entry = {'delivery_no':item.get('delivery_no'),'status':'blocked'}
        try:
            _,_,_,target,_ = verify(item,settings)
            entry.update(status='ready',target=str(target))
        except Exception as exc: entry['reason'] = str(exc)
        results.append(entry)
    # Preflight ALL items before any mutation; block the entire execution batch on conflict.
    if execute and not any(r['status']=='blocked' for r in results):
        journal_path = Path(str(report)+'.journal.jsonl')
        with journal_path.open('x',encoding='utf-8') as journal:
            def log(value):
                journal.write(json.dumps(value,ensure_ascii=False)+'\n'); journal.flush(); os.fsync(journal.fileno())
            log({'event':'batch_start'})
            for item,entry in zip(items,results):
                try:
                    source,backup,ledger,target,h = verify(item,settings)
                    target.parent.mkdir(exist_ok=True)
                    existed = target.exists()
                    if not existed:
                        with source.open('rb') as src,target.open('xb') as dst:
                            shutil.copyfileobj(src,dst); dst.flush(); os.fsync(dst.fileno())
                    # Full readback again before cleanup, including workbook and original backup.
                    verify(item,settings)
                    if digest(target) != h: raise ValueError('Archive hash mismatch')
                    log({'event':'archive_verified','target':str(target),'sha256':h})
                    removed = source.exists()
                    if removed:
                        if digest(source) != h or digest(ledger) != item['ledger_sha256'].lower(): raise ValueError('Changed before cleanup')
                        source.unlink()
                    entry.update(status='completed' if removed else 'already_complete',archive='reused' if existed else 'copied',source_removed=removed,sha256=h)
                except Exception as exc:
                    entry.update(status='blocked',reason=str(exc))
                log(entry)
    with report.open('x',encoding='utf-8') as f: json.dump({'execute':execute,'results':results},f,ensure_ascii=False,indent=2)
    return results


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True);p.add_argument('--report',required=True);p.add_argument('--execute',action='store_true')
    p.add_argument('--settings',default=str(Path(__file__).parent.parent/'assets/settings.json'))
    a=p.parse_args()
    result=run(json.loads(Path(a.manifest).read_text(encoding='utf-8-sig')),json.loads(Path(a.settings).read_text(encoding='utf-8-sig')),a.report,a.execute)
    print(json.dumps({'statuses':[r['status'] for r in result]},ensure_ascii=False))
    raise SystemExit(2 if any(r['status']=='blocked' for r in result) else 0)
