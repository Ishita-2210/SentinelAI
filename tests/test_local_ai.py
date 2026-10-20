"""Local AI unit tests: fake IPC/model outputs; no weight loading."""
from datetime import datetime,timedelta,timezone
import json
import queue
import threading
import pytest
from backend.ai_runtime.process import ModelProcess,ModelUnavailable,ModelBusy
from backend.llm.assistant import LLMAssistant,validated_order
from backend.config.settings import LLMConfig,Settings
from backend.schemas.event import Event
from backend.retrival.retrival import EventRetriever
from backend.retrival.questions import question_filters

def test_model_disabled_never_launches_process(monkeypatch):
    monkeypatch.setattr("subprocess.Popen",lambda *a,**kw:pytest.fail("Unexpected model process"))
    model=ModelProcess("llm","test",enabled=False);model.start()
    assert model.snapshot()["state"]=="disabled"
    with pytest.raises(ModelUnavailable):model.request({})
def test_loading_state_is_not_ready():
    model=ModelProcess("vlm","test",enabled=True)
    assert model.snapshot()["state"]=="loading"
    with pytest.raises(ModelUnavailable):model.request({})
    model._fail("missing local weights")
    assert model.snapshot()["state"]=="error"
    assert model.snapshot()["error"]=="missing local weights"

@pytest.fixture
def ipc(monkeypatch,tmp_path):
    from backend.ai_runtime import process
    monkeypatch.setattr(process,"ROOT",tmp_path)
    class FakeProcess:
        returncode=None
        def __init__(self,*args,**kwargs):
            self.messages=queue.Queue();self.messages.put(json.dumps({"type":"ready","meta":{"device":"cpu"}})+"\n")
            self.stdin=self
            self.stdout=self.iterate()
        def write(self,line):
            data=json.loads(line)
            if "id" in data:
                self.messages.put(json.dumps({"type":"result","id":data["id"],"data":{"text":"{\"event_ids\":[1]}","generated_tokens":8,"input_tokens":20}})+"\n")
        def flush(self):pass
        def iterate(self):
            while True:
                value=self.messages.get()
                if value is None:return
                yield value
        def poll(self):return self.returncode
        def terminate(self):self.returncode=0;self.messages.put(None)
        def kill(self):self.terminate()
        def wait(self,timeout=None):return self.returncode or 0
    monkeypatch.setattr(process.subprocess,"Popen",FakeProcess)
    model=ModelProcess("llm","test",enabled=True)
    model.start();assert model._ready.wait(1)
    yield model
    model.stop()

def test_model_ready_and_reuses_one_process(ipc):
    assert ipc.snapshot()["state"]=="ready"
    child=ipc._proc
    assert ipc.request({"messages":[]})["generated_tokens"]==8
    assert ipc.request({"messages":[]})["generated_tokens"]==8
    assert ipc._proc is child

def test_busy_inference_rejected_without_backlog(ipc):
    ipc._request_lock.acquire()
    try:
        with pytest.raises(ModelBusy):ipc.request({})
    finally:ipc._request_lock.release()

def test_loading_deadline_reports_error():
    model=ModelProcess("vlm","test",enabled=True)
    model._loading_expired()
    assert model.snapshot()["state"]=="error"

@pytest.mark.parametrize("raw",[
    '{"event_ids":[999]}','{"event_ids":[1,1]}','{"event_ids":[true]}',
    '{"event_ids":[1],"summary":"invented"}','Invented event happened','[]'])
def test_hallucinated_or_malformed_selection_is_rejected(raw):
    with pytest.raises((ValueError,TypeError)):validated_order(raw,[1,2])
def test_valid_order_retains_all_retrieved_facts():
    assert validated_order('{"event_ids":[2]}',[1,2,3])==[2,1,3]

def fixture_rows():
    return [dict(id=1,event_type="LOITERING",timestamp="2026-10-20T10:00:00+00:00",
                 track_id=4,zone="entrance",description="recorded",evidence_path=None,vlm_answer=None)]
class FakeModel:
    def __init__(self,state="ready",text='{"event_ids":[1]}'):
        self.state,self.text=state,text
    def snapshot(self):return {"state":self.state,"error":"load failed" if self.state=="error" else None}
    def request(self,payload):return {"text":self.text,"generated_tokens":8,"input_tokens":30}

@pytest.mark.parametrize("state",["disabled","loading","error"])
def test_qa_model_unavailable_still_returns_recorded_facts(state):
    assistant=LLMAssistant(LLMConfig(),service=FakeModel(state))
    result=assistant.query("What happened?",fixture_rows())
    assert result["llm_status"]==state and result["llm_used"] is False
    assert result["source_event_ids"]==[1]
    assert "2026-10-20T10:00:00+00:00" in result["answer"]
def test_qa_generation_cannot_add_facts():
    assistant=LLMAssistant(LLMConfig(),service=FakeModel(text='{"event_ids":[999]}'))
    result=assistant.query("What happened?",fixture_rows())
    assert result["generation_status"]=="inconclusive_selection"
    assert result["source_event_ids"]==[1]
    assert "999" not in result["answer"]
def test_qa_valid_model_selection():
    result=LLMAssistant(LLMConfig(),service=FakeModel()).query("What happened?",fixture_rows())
    assert result["generation_status"]=="validated" and result["llm_used"]
def test_no_evidence_is_explicit_and_skips_generation():
    result=LLMAssistant(LLMConfig(),service=FakeModel()).query("Any event?",[])
    assert result["generation_status"]=="no_evidence" and result["source_event_ids"]==[]
    assert result["llm_used"] is False

def test_time_window_filters_actual_database(tmp_db):
    now=datetime(2026,10,20,10,tzinfo=timezone.utc)
    recent=tmp_db.save_event(Event("LOITERING",1,"person",now-timedelta(minutes=2)))
    tmp_db.save_event(Event("LOITERING",2,"person",now-timedelta(minutes=20)))
    rows,filters=EventRetriever(tmp_db).for_question("What events occurred in the last five minutes?",now=now)
    assert [x["id"] for x in rows]==[recent]
def test_latest_and_specific_event_filters(tmp_db):
    now=datetime.now(timezone.utc)
    a=tmp_db.save_event(Event("LOITERING",1,"person",now-timedelta(minutes=1)))
    b=tmp_db.save_event(Event("LOITERING",2,"person",now))
    rows,_=EventRetriever(tmp_db).for_question("When was the latest loitering event?")
    assert [x["id"] for x in rows]==[b]
    rows,_=EventRetriever(tmp_db).for_question("Show evidence for event #"+str(a))
    assert [x["id"] for x in rows]==[a]
def test_around_requires_explicit_timezone():
    with pytest.raises(ValueError):question_filters("What happened around 2026-10-20T10:00:00?")
    assert "start" in question_filters("What happened around 2026-10-20T10:00:00+05:30?")
def test_verification_fields_migrate_without_losing_event(tmp_db):
    ident=tmp_db.save_event(Event("LOITERING",1,"person",datetime.now(timezone.utc)))
    tmp_db.set_verification(ident,"inconclusive","Is a person visible?","model","yes","yes",True)
    row=dict(tmp_db.get_event_by_id(ident))
    assert row["vlm_status"]=="inconclusive" and row["event_type"]=="LOITERING"
    assert row["vlm_prompt"]=="Is a person visible?"
    rows,_=EventRetriever(tmp_db).for_question("Which events have VLM verification results?")
    assert [x["id"] for x in rows]==[ident]

def test_vlm_queue_deduplicates_and_prioritizes(tmp_db,tmp_path):
    from backend.ai_runtime.manager import AIManager
    cfg=Settings();cfg.vlm.enabled=True
    ai=AIManager(cfg,tmp_db)
    image=tmp_path/"evidence.jpg";image.write_bytes(b"unit fixture, no model reads it")
    a=tmp_db.save_event(Event("LOITERING",1,"person",datetime.now(timezone.utc)))
    b=tmp_db.save_event(Event("UNATTENDED_OBJECT",2,"backpack",datetime.now(timezone.utc)))
    assert ai.enqueue_event(a,"LOITERING",str(image))=="queued"
    assert ai.enqueue_event(a,"LOITERING",str(image))=="already_queued"
    assert ai.enqueue_event(b,"UNATTENDED_OBJECT",str(image))=="queued"
    assert ai._queue.get_nowait()[2]==b
def test_model_enable_flags_override_yaml(monkeypatch):
    from backend.main import _parse_args
    monkeypatch.setattr("sys.argv",["sentinel","--vlm","--no-llm"])
    args=_parse_args()
    assert args.vlm_enabled is True and args.llm_enabled is False


def test_api_model_states_qa_and_saved_evidence(tmp_db,tmp_path,monkeypatch):
    from backend.api import create_app,routes
    from backend.ai_runtime.manager import AIManager
    from fastapi.testclient import TestClient
    cfg=Settings();cfg.vlm.enabled=True
    cfg.evidence.output_dir=str(tmp_path/"events")
    evidence=tmp_path/"events"/"fixture.jpg";evidence.parent.mkdir();evidence.write_bytes(b"mock image")
    cfg.database.path=str(tmp_path/"unused.db")
    monkeypatch.setattr("backend.config.settings.get_settings",lambda:cfg)
    ident=tmp_db.save_event(Event("LOITERING",4,"person",datetime.now(timezone.utc)),str(evidence))
    ai=AIManager(cfg,tmp_db)
    assistant=LLMAssistant(LLMConfig(),service=FakeModel(text=json.dumps({"event_ids":[ident]})))
    monkeypatch.setattr(routes,"_db",tmp_db);monkeypatch.setattr(routes,"_retriever",EventRetriever(tmp_db))
    monkeypatch.setattr(routes,"_llm",assistant);monkeypatch.setattr(routes,"_ai",ai)
    with TestClient(create_app()) as client:
        health=client.get("/api/health").json()
        assert health["models"]["vlm"]["state"]=="loading"
        result=client.post("/api/llm/query",json={"question":"Latest loitering event"}).json()
        assert result["generation_status"]=="validated"
        assert result["source_event_ids"]==[ident]
        assert client.get("/api/models").json()["vlm"]["state"]=="loading"
        assert client.post("/api/events/"+str(ident)+"/verify").status_code==202
        stored=client.get("/api/events/"+str(ident)).json()
        assert stored["vlm_status"]=="queued"
        assert stored["evidence_path"]==str(evidence)
        assert client.post("/api/llm/query",json={"question":""}).status_code==422
        assert client.post("/api/events/999999/verify").status_code==404


def test_model_limits_reject_non_integer_threads():
    from backend.config.settings import validate_settings
    cfg=Settings();cfg.llm.cpu_threads=1.5
    with pytest.raises(ValueError):validate_settings(cfg)

def test_queued_verification_cancelled_on_shutdown(tmp_db,tmp_path):
    from backend.ai_runtime.manager import AIManager
    cfg=Settings();cfg.vlm.enabled=True
    ai=AIManager(cfg,tmp_db)
    image=tmp_path/"image.jpg";image.write_bytes(b"mock image")
    ident=tmp_db.save_event(Event("LOITERING",1,"person",datetime.now(timezone.utc)))
    assert ai.enqueue_event(ident,"LOITERING",str(image))=="queued"
    ai.stop()
    assert tmp_db.get_event_by_id(ident)["vlm_status"]=="cancelled"

def test_network_camera_has_bounded_open_and_read_timeouts(monkeypatch):
    import cv2
    from backend.camera.camera import CameraSource
    calls=[]
    class Capture:
        def isOpened(self):return True
        def set(self,*args):pass
        def get(self,*args):return 0
        def release(self):pass
    monkeypatch.setattr(cv2,"VideoCapture",lambda *args:(calls.append(args) or Capture()))
    with CameraSource("http://127.0.0.1:9/stream"):pass
    assert calls[0][1]==cv2.CAP_FFMPEG
    parameters=dict(zip(calls[0][2][::2],calls[0][2][1::2]))
    assert 0<parameters[cv2.CAP_PROP_OPEN_TIMEOUT_MSEC]<=5000
    assert 0<parameters[cv2.CAP_PROP_READ_TIMEOUT_MSEC]<=3000


def test_qa_sources_follow_validated_answer_order():
    events=[dict(id=i,event_type="LOITERING",track_id=i,timestamp="2026-10-20T00:00:00+00:00",
                 evidence_path=f"/evidence/{i}.jpg") for i in (1,2)]
    assistant=LLMAssistant(LLMConfig(),service=FakeModel(text='{"event_ids":[2]}'))
    result=assistant.query("Show events",events)
    assert result["source_event_ids"]==[2,1]
    assert [source["id"] for source in result["sources"]]==[2,1]
    assert result["answer"].index("Event #2")<result["answer"].index("Event #1")


def test_successful_inference_count_requires_a_real_worker_reply(ipc):
    assert ipc.snapshot()["inference_count"]==0
    ipc.request({"messages":[]})
    assert ipc.snapshot()["inference_count"]==1
    assert ipc.snapshot()["last_inference_at"] is not None
