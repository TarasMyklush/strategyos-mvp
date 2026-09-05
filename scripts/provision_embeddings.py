"""Explicit operator step: download pinned weights, then seal a local manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strategyos_mvp.semantic_embeddings import MODEL_NAME,MODEL_REPOSITORY,MODEL_REVISION,DIMENSIONS,MODEL_FILE


def provision(destination):
    from huggingface_hub import snapshot_download
    destination=Path(destination).resolve()
    snapshot_download(repo_id=MODEL_REPOSITORY,revision=MODEL_REVISION,local_dir=str(destination),
                      allow_patterns=[MODEL_FILE,'*.json','README.md'])
    manifest={'model_name':MODEL_NAME,'repository':MODEL_REPOSITORY,'revision':MODEL_REVISION,'dimensions':DIMENSIONS,
              'files':{str(path.relative_to(destination)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(destination.rglob("*"))
                       if path.is_file() and '.cache' not in path.parts and path.name not in {'model-manifest.json','revision.json'}}}
    (destination/'model-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True)
    print(json.dumps(provision(parser.parse_args().destination),indent=2))
