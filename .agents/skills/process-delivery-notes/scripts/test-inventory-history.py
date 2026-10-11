import csv,hashlib,importlib.util,tempfile
from pathlib import Path

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

m=load('inventory','inventory-pending.py')
with tempfile.TemporaryDirectory(prefix='delivery-inventory-test-') as tmp:
    root=Path(tmp);pending=root/'pending';pending.mkdir();batch=root/'batch-20260101';batch.mkdir()
    image=pending/'renamed.png';image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
    digest=hashlib.sha256(image.read_bytes()).hexdigest()
    for name in ('gs-result.csv','wh-manifest.csv'):
        with (batch/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['delivery_no','source_sha256']);w.writeheader();w.writerow({'delivery_no':'TEST-WH-00001','source_sha256':digest})
    (pending/'ignored.txt').write_text('not an image')
    result=m.inventory({'pending_root':str(pending)},root)
    assert result['total_files']==1 and result['historical_hash_candidates']==1
    assert len(result['files'][0]['historical_candidates'])==2
    assert image.exists()
print('History inventory passed: carrier results, manifests, renamed source hash and read-only behavior')
