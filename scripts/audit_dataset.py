"""Read-only split audit; reports overlap without changing any records."""
import collections
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from evaluate_vlm import metrics
def main():
    data={s:[json.loads(l) for l in (ROOT/"dataset"/(s+".jsonl")).read_text().splitlines() if l.strip()] for s in ("train","val","test")}
    def digest(x):return hashlib.sha256((ROOT/"dataset"/x["image_path"]).read_bytes()).hexdigest()
    hashes={s:{digest(x) for x in rows} for s,rows in data.items()}
    report={"splits":{},"overlaps":{}}
    for s,rows in data.items():
        report["splits"][s]=dict(records=len(rows),labels=dict(collections.Counter(x["answer"] for x in rows)),
            unique_image_hashes=len(hashes[s]),sha256=hashlib.sha256((ROOT/"dataset"/(s+".jsonl")).read_bytes()).hexdigest())
    for a,b in (("train","val"),("train","test"),("val","test")):
        report["overlaps"][a+"_"+b]=dict(scene_ids=len({x["scene_id"] for x in data[a]}&{x["scene_id"] for x in data[b]}),
            image_hashes=len(hashes[a]&hashes[b]))
    excluded=hashes["train"]|hashes["val"]
    kept=[i for i,x in enumerate(data["test"]) if digest(x) not in excluded]
    report["test_nonoverlap_indices"]=kept
    report["test_nonoverlap_n"]=len(kept)
    report["test_nonoverlap_labels"]=dict(collections.Counter(data["test"][i]["answer"] for i in kept))
    report["test_records_overlapping_training"]=sum(digest(x) in hashes["train"] for x in data["test"])
    report["subset_metrics"]={}
    for name in ("base","adapter"):
        p=ROOT/"data/evaluation/vlm_compatible"/(name+"_predictions.jsonl")
        if p.exists():
            predictions=[json.loads(x) for x in p.read_text().splitlines()]
            if len(predictions)==len(data["test"]):
                report["subset_metrics"][name]=metrics([x for x in predictions if x["index"] in kept])
    out=ROOT/"data/evaluation/dataset_audit.json"
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
