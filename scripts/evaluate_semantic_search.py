"""Score a preselected retrieval corpus without changing its questions or labels."""
import argparse
import json
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strategyos_mvp.semantic_embeddings import embed, MODEL_REVISION

parser=argparse.ArgumentParser();parser.add_argument('--corpus',required=True);parser.add_argument('--output',required=True)
args=parser.parse_args();corpus=json.loads(Path(args.corpus).read_text());pairs=corpus['pairs'];start=time.monotonic()
vectors=[embed(item['document']) for item in pairs];rows=[]
for item in pairs:
    vector=embed(item['question'],query=True)
    ranked=sorted(range(len(pairs)),key=lambda index:sum(a*b for a,b in zip(vector,vectors[index])),reverse=True)
    ids=[pairs[index]['id'] for index in ranked[:3]]
    rows.append({'id':item['id'],'top3':ids,'correct_at_1':ids[0]==item['id'],'correct_at_3':item['id'] in ids})
recall=sum(item['correct_at_3'] for item in rows)/len(rows)
result={'model_revision':MODEL_REVISION,'questions':len(rows),'recall_at_3':recall,'duration_seconds':round(time.monotonic()-start,3),'rows':rows,'passed':recall>=corpus['threshold']['recall_at_3']}
Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({key:value for key,value in result.items() if key!='rows'}))
raise SystemExit(0 if result['passed'] else 1)
