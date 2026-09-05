"""Materialize one runtime pack from canonical demo sources, preserving hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def build(destination: Path):
    repo = Path(__file__).resolve().parents[1]
    destination = destination.resolve()
    if destination.exists():
        raise ValueError('Choose a new destination; existing packs are immutable.')
    files=[]
    for source, prefix in ((repo/'data/demo/01_Synthetic_Dataset',Path('.')),
                           (repo/'data/demo/04_Strategic_Context',Path('25_Strategic_Context'))):
        for path in sorted(source.rglob('*')):
            if not path.is_file() or path.name.startswith('.') or path.name.lower().startswith('readme'):
                continue
            relative=prefix/path.relative_to(source)
            files.append({'canonical_path':path.relative_to(repo).as_posix(),'pack_path':relative.as_posix(),
                          'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    manifest={'version':1,'classification':'synthetic_demo','period':'2026-06','actual_external_connections':False,'files':files}
    digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    destination.mkdir(parents=True)
    for entry in files:
        target=destination/entry['pack_path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(repo/entry['canonical_path'],target)
    (destination/'release-source-manifest.json').write_text(json.dumps({**manifest,'digest':digest},indent=2))
    return {'destination':str(destination),'file_count':len(files),'source_digest':digest}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().destination),indent=2))
