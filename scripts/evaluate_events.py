"""Synthetic track scenarios: software correctness only, NOT field accuracy."""
import collections
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.schemas.track import Track
from backend.schemas.bounding_box import BoundingBox
from backend.state_manager.state_manager import StateManager
from backend.event_engine.event_engine import EventEngine
from backend.event_engine.zone import Zone
T=datetime(2026,10,20)
def person(x=100,tid=1):return Track(tid,0,"person",.95,BoundingBox(x,100,x+80,300))
def bag(x=220):return Track(2,24,"backpack",.95,BoundingBox(x,210,x+40,250))
def scenarios():
    return [
      ("entry_exit",[(0,[person()]),(.2,[person()]),(1.3,[])],["PERSON_ENTERED","PERSON_EXITED"]),
      ("temporary_loss",[(0,[person()]),(.1,[]),(.2,[person()])],["PERSON_ENTERED"]),
      ("loiter_once",[(0,[person()]),(2,[person()]),(3,[person()]),(4,[person()])],["PERSON_ENTERED","LOITERING"]),
      ("leave_reenter",[(0,[person()]),(1,[person(2500)]),(2,[person()])],["PERSON_ENTERED","PERSON_EXITED","RUNNING","PERSON_ENTERED"]),
      ("zone_change",[(0,[person()]),(1,[person(1200)])],["PERSON_ENTERED","ZONE_CHANGED","RUNNING"]),
      ("slow_zone_change",[(0,[person(950)]),(1,[person(1010)])],["PERSON_ENTERED","ZONE_CHANGED"]),
      ("running_burst",[(0,[person()]),(.033,[person(130)]),(.066,[person(160)])],["PERSON_ENTERED","RUNNING"]),
      ("normal_motion",[(0,[person()]),(1,[person(110)]),(1.5,[person(115)])],["PERSON_ENTERED"]),
      ("empty",[(0,[]),(10,[])],[]),
      ("unowned_object",[(i*.1,[bag()]) for i in range(40)],[]),
      ("owner_present",[(i*.1,[person(),bag()]) for i in range(18)],["PERSON_ENTERED"]),
      ("owner_leaves",[(0,[person(),bag()])]+[(i*.1,[bag()]) for i in range(1,40)],["PERSON_ENTERED","PERSON_EXITED","UNATTENDED_OBJECT"]),
      ("moving_object",[(0,[person(),bag()])]+[(i*.1,[bag(220+i*30)]) for i in range(1,35)],["PERSON_ENTERED","PERSON_EXITED"]),
    ]
def main():
    rows=[];total=collections.Counter();types={}
    for name,frames,expected in scenarios():
        sm,ee=StateManager(),EventEngine()
        ee.loitering_threshold=2;ee.unattended_threshold=1
        ee.zones.append(Zone("second",1001,0,2000,1000))
        predicted=[]
        for seconds,tracks in frames:
            stamp=T+timedelta(seconds=seconds)
            predicted += [e.event_type for e in ee.update(sm.update(tracks,stamp),stamp)]
        g,p=collections.Counter(expected),collections.Counter(predicted)
        tp=sum((g&p).values());fp=sum((p-g).values());fn=sum((g-p).values())
        total.update(tp=tp,fp=fp,fn=fn)
        for kind in set(g)|set(p):
            c=types.setdefault(kind,collections.Counter())
            c.update(tp=min(g[kind],p[kind]),fp=max(0,p[kind]-g[kind]),fn=max(0,g[kind]-p[kind]))
        rows.append(dict(name=name,expected=expected,predicted=predicted,tp=tp,fp=fp,fn=fn))
    def score(c):
        tp,fp,fn=c["tp"],c["fp"],c["fn"]
        precision=tp/(tp+fp) if tp+fp else None
        recall=tp/(tp+fn) if tp+fn else None
        return dict(c,precision=precision,recall=recall,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)
    report=dict(kind="synthetic deterministic track scenarios; count-matching within each sequence",
                sequences=len(rows),expected_events=sum(len(x["expected"]) for x in rows),
                metrics=score(total),per_type={k:score(v) for k,v in types.items()},
                false_positives_per_sequence=total["fp"]/len(rows),scenarios=rows,
                limitation="No real video ground truth; does not measure detector, ID switches or event timing accuracy")
    out=ROOT/"data/evaluation/events.json";out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    return 1 if total["fp"] or total["fn"] else 0
if __name__=="__main__":sys.exit(main())
