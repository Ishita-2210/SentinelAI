"""Explicit integration test: real local weights; never part of pytest."""
import json
from pathlib import Path
import sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.config.settings import Settings
from backend.database.event_database import EventDatabase
from backend.retrival.retrival import EventRetriever
from backend.ai_runtime.manager import AIManager
def main():
    cfg=Settings();cfg.vlm.enabled=True;cfg.llm.enabled=True
    cfg.database.path="data/demo/sentinelai.db";cfg.evidence.output_dir="data/demo/events"
    db=EventDatabase(str(ROOT/cfg.database.path));retriever=EventRetriever(db)
    ai=AIManager(cfg,db);out=ROOT/"data/integration";out.mkdir(parents=True,exist_ok=True);report={}
    try:
        ai.start();deadline=time.monotonic()+200;last=None
        while time.monotonic()<deadline:
            states={k:v["state"] for k,v in ai.snapshot().items()}
            if states!=last:print(states,flush=True);last=states
            if all(x=="ready" for x in states.values()):break
            if any(x=="error" for x in states.values()):raise RuntimeError(str(ai.snapshot()))
            time.sleep(.5)
        assert all(v["state"]=="ready" for v in ai.snapshot().values()),ai.snapshot()
        events=retriever.get_recent(3);assert events,"Run the real-inference demo first"
        ev=next(x for x in events if x.get("evidence_path") and Path(x["evidence_path"]).is_file())
        report["enqueue"]=ai.enqueue_event(ev["id"],ev["event_type"],ev["evidence_path"],ev["class_name"],ev["zone"],force=True)
        result=ai.llm.query("Summarize the latest recorded events.",events);report["llm"]=result
        assert result["llm_used"] and result["generated_tokens"]>0 and result["generation_status"]=="validated",result
        deadline=time.monotonic()+75
        while time.monotonic()<deadline:
            checked=retriever.get_by_id(ev["id"])
            if checked.get("vlm_status") in {"inconclusive","error"}:break
            time.sleep(.2)
        report["vlm_event"]=checked
        assert checked["vlm_status"]=="inconclusive" and checked["vlm_raw_text"],checked
        report["models"]=ai.snapshot();report["status"]="passed"
    except Exception as exc:report.update(status="failed",error=str(exc),models=ai.snapshot())
    finally:
        ai.stop();db.close()
        (out/"local_models.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    return 0 if report["status"]=="passed" else 1
if __name__=="__main__":sys.exit(main())
