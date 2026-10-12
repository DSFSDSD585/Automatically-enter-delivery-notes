"""Generate runtime mappings from the sole business-rules appendix."""
import argparse
import csv
import io
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def mappings(root=ROOT):
    text = (Path(root)/'references/送货单业务逻辑规则.md').read_text(encoding='utf-8-sig')
    block = text.split('<!-- DELIVERY_MAPPINGS_START -->',1)[1].split('<!-- DELIVERY_MAPPINGS_END -->',1)[0]
    data = json.loads(block.split('```json',1)[1].split('```',1)[0])
    for item in data['carriers']['rules']:
        re.compile(item['pattern'])
    if len({p['alias'] for p in data['projects']}) != len(data['projects']):
        raise ValueError('duplicate_project_alias')
    return data


def outputs(root=ROOT):
    d = mappings(root)
    out = io.StringIO(newline='')
    w = csv.DictWriter(out, fieldnames=list(d['projects'][0]), lineterminator='\n')
    w.writeheader(); w.writerows(d['projects'])
    return {'project-map.csv': out.getvalue(), 'carrier-rules.json':json.dumps(d['carriers'],ensure_ascii=False,indent=2)+'\n',
            'verified-aliases.json':json.dumps({k:d[k] for k in ('note_aliases','brand_aliases','seller_candidates')},ensure_ascii=False,indent=2)+'\n'}


def check_path(name, root=ROOT):
    path = Path(root)/'references'/name
    if name == 'project-map.csv' and not path.exists():
        return path.with_name('project-map.example.csv')
    return path


def note_candidates(raw, project, data=None):
    """Search candidates only: preserves zeros/suffixes and confines reviewed aliases."""
    data = data or mappings()
    value = str(raw).strip().upper()
    candidates = {value}
    for item in data['note_aliases']:
        group = {item['canonical'], *item['aliases']}
        if project == item['project'] and value in group:
            candidates.update(group)
    return candidates


def date_parts(raw, confirmed_year=None):
    """Extract an unambiguous calendar date while retaining its original annotation."""
    text = str(raw).strip()
    m = re.fullmatch(r'(?:(\d{4})[年/.-])?(\d{1,2})[月/.-](\d{1,2})日?(.*)', text)
    if not m or not (m[1] or confirmed_year):
        raise ValueError('date_or_year_needs_review')
    result = date(int(m[1] or confirmed_year), int(m[2]), int(m[3]))
    return {'raw':raw, 'date':result.isoformat(), 'annotation':m[4].strip()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--write',action='store_true');p.add_argument('--check',action='store_true');a=p.parse_args()
    if a.write == a.check: p.error('choose --write or --check')
    for name,content in outputs().items():
        path=ROOT/'references'/name
        if a.write: path.write_text(content,encoding='utf-8',newline='\n')
        elif not check_path(name).is_file() or check_path(name).read_text(encoding='utf-8-sig') != content: raise ValueError('derived_mapping_drift: '+name)
    print('mapping derivation verified' if a.check else 'runtime mappings generated')


if __name__=='__main__':main()
