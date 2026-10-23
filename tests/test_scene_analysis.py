"""Synthetic images and mocked model services. No hardware or real weights."""
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
import threading

from PIL import Image
import pytest

from backend.ai_runtime.manager import AIManager
from backend.config.settings import Settings, LLMConfig
from backend.llm.assistant import LLMAssistant
from backend.vlm_runtime.verifier import VisualVerifier
from tests.test_local_ai import FakeModel, fixture_rows


@pytest.mark.parametrize('fail',[False,True])
def test_scene_caption_bypasses_and_restores_loaded_presence_adapter(fail):
    active = {'adapter':True}
    @contextmanager
    def disable():
        active['adapter'] = False
        try:yield
        finally:active['adapter'] = True
    class Tensor:
        def to(self,*args):return self
    class Processor:
        def __call__(self,**kwargs):
            assert kwargs['text'] == '<DETAILED_CAPTION>'
            return {'input_ids':Tensor()}
        def batch_decode(self,*args,**kwargs):
            assert kwargs['skip_special_tokens'] is False
            return ['A person beside a table.']
        def post_process_generation(self,text,task,image_size):return {task:text}
    def generate(**kwargs):
        assert not active['adapter']
        assert kwargs['max_new_tokens'] >= 64
        if fail:raise RuntimeError('simulated caption failure')
        return [1]
    verifier = VisualVerifier(enabled=False)
    verifier.enabled = True; verifier._adapter_loaded = True
    verifier._model = SimpleNamespace(disable_adapter=disable,generate=generate)
    verifier._processor = Processor(); verifier._torch = SimpleNamespace(no_grad=nullcontext)
    result = verifier.describe(Image.new('RGB',(8,8)))
    assert active['adapter'] is True and verifier.adapter_loaded is True
    assert result.task == '<DETAILED_CAPTION>' and result.adapter_loaded is False
    assert bool(result.error) == fail
    if not fail:assert result.raw_text == 'A person beside a table.'


def test_written_explanation_requests_prose_with_original_sources():
    class Prose(FakeModel):
        def request(self,payload):
            assert payload['task'] == 'explain'
            assert 'allowed_event_ids' not in payload
            assert payload['context_events'][0]['visual_description'] == 'A person beside a table.'
            assert '"id"' not in payload['messages'][1]['content']
            return dict(text='A person is visible beside a table.',generated_tokens=10,input_tokens=80,context_event_ids=[1])
    rows = fixture_rows()
    rows[0].update(vlm_status='inconclusive',vlm_task='<DETAILED_CAPTION>',vlm_raw_text='A person beside a table.')
    result = LLMAssistant(LLMConfig(),service=Prose()).explain('Describe the image.',rows)
    assert result['answer_kind'] == 'model_explanation' and result['llm_used']
    assert result['source_event_ids'] == [1] and result['answer'] == 'A person is visible beside a table.'


@pytest.mark.parametrize('text',['', '{"event_ids":[1]}', 'Event #999 describes an intruder.', 'Event ID 999 describes an intruder.', 'See https://invented.invalid/evidence'])
def test_bad_prose_does_not_get_displayed_as_a_grounded_explanation(text):
    result = LLMAssistant(LLMConfig(),service=FakeModel(text=text)).explain('Describe.',fixture_rows())
    assert result['generation_status'] == 'error'
    assert result['answer_kind'] == 'recorded_facts' and not result['llm_used']


def test_scene_explanation_falls_back_to_real_caption_when_llm_unavailable():
    assistant = LLMAssistant(LLMConfig(enabled=False))
    result = assistant.explain('Describe.',[],scene={'caption':'A person beside a table.'})
    assert result['answer_kind'] == 'visual_observation' and not result['llm_used']
    assert 'A person beside a table.' in result['answer']
    assert result['source_event_ids'] == []


def test_explanation_rejects_generation_without_retained_event_context():
    class NoContext(FakeModel):
        def request(self,payload):return dict(text='An unsupported scene.',context_event_ids=[])
    result = LLMAssistant(LLMConfig(),service=NoContext()).explain('Describe.',fixture_rows())
    assert result['generation_status'] == 'error' and result['answer_kind'] == 'recorded_facts'


def test_narrative_context_trimming_keeps_ids_out_of_model_text():
    import json
    from backend.ai_runtime.worker import prepare_llm_inputs
    observed = []
    class Tokenizer:
        def apply_chat_template(self,messages,**kwargs):
            observed.append(messages)
            return json.dumps(messages)
        def __call__(self,text,**kwargs):return {'input_ids':SimpleNamespace(shape=(1,len(text)))}
    context = [{'id':101,'description':'a'*100},{'id':202,'description':'b'*100}]
    visible = [{'description':event['description']} for event in context]
    request = dict(task='explain',context_events=context,question='Describe.',messages=[
        {'role':'system','content':'Use observations only.'},
        {'role':'user','content':'Events: '+json.dumps(visible)+'\nQuestion: Describe.'}])
    _, allowed = prepare_llm_inputs(Tokenizer(),request,max_tokens=310)
    assert allowed == [101]
    assert all('"id"' not in messages[1]['content'] for messages in observed)


def test_preview_snapshot_keeps_bytes_and_sequence_together(monkeypatch):
    from backend.api import routes
    monkeypatch.setattr(routes,'_latest_jpeg',None);monkeypatch.setattr(routes,'_preview_info',(None,0))
    monkeypatch.setattr(routes,'_live_state',dict(routes._live_state,camera_ok=True))
    routes.update_preview(b'first frame')
    captured = routes._preview_snapshot()
    routes.update_preview(b'second frame')
    assert captured[0] == b'first frame' and routes.preview_status(captured)['preview_sequence'] == 1
    assert routes._preview_snapshot()[0] == b'second frame' and routes.preview_status()['preview_sequence'] == 2


def test_scene_queue_shares_worker_and_keeps_exact_snapshot(tmp_db,tmp_path):
    cfg = Settings(); cfg.vlm.enabled = True; cfg.evidence.output_dir = str(tmp_path/'images')
    manager = AIManager(cfg,tmp_db)
    started, release = threading.Event(),threading.Event()
    def caption(payload,**kwargs):
        started.set(); assert release.wait(2)
        assert payload['task'] == 'caption'
        from pathlib import Path
        assert Path(payload['image_path']).read_bytes() == b'original synthetic JPEG'
        return dict(task='<DETAILED_CAPTION>',raw_text='A person beside a table.',model_id='simulated')
    manager.vlm.request = caption
    manager.llm.explain = lambda *args,**kwargs:dict(answer='A person is beside a table.',answer_kind='model_explanation',
        generation_status='generated',llm_used=True,model='simulated')
    status, scene = manager.enqueue_scene(b'original synthetic JPEG',{'preview_sequence':1,'source_kind':'synthetic'})
    assert status == 'queued' and tmp_db.count_events() == 0  # Never fabricate a detection event.
    manager._thread = threading.Thread(target=manager._worker); manager._thread.start()
    try:
        assert started.wait(2)
        again, pending = manager.enqueue_scene(b'a later frame',{'preview_sequence':2})
        assert again == 'already_queued' and pending['id'] == scene['id']
        release.set(); manager._queue.join()
        result = manager.scene_snapshot()
        assert result['state'] == 'completed' and result['caption'] == 'A person beside a table.'
        assert result['explanation_kind'] == 'model_explanation' and result['llm_used']
        assert manager.enqueue_scene(b'same sequence',{'preview_sequence':1})[0] == 'already_analyzed'
        result['caption'] = 'caller mutation'
        assert manager.scene_snapshot()['caption'] != 'caller mutation'
    finally:release.set(); manager.stop()


def test_scene_api_rejects_stale_frames_and_enqueues_only_actual_preview(tmp_db,tmp_path,monkeypatch):
    from backend.api import create_app,routes
    from backend.retrival.retrival import EventRetriever
    from fastapi.testclient import TestClient
    cfg = Settings(); cfg.vlm.enabled = True; cfg.evidence.output_dir = str(tmp_path/'images')
    monkeypatch.setattr('backend.config.settings.get_settings',lambda:cfg)
    manager = AIManager(cfg,tmp_db)
    monkeypatch.setattr(routes,'_db',tmp_db); monkeypatch.setattr(routes,'_retriever',EventRetriever(tmp_db))
    monkeypatch.setattr(routes,'_ai',manager)
    monkeypatch.setattr(routes,'_latest_jpeg',None); monkeypatch.setattr(routes,'_preview_info',(None,0))
    monkeypatch.setattr(routes,'_live_state',dict(routes._live_state,camera_ok=True,source_kind='synthetic'))
    with TestClient(create_app()) as client:
        assert client.post('/api/scene').status_code == 409
        routes.update_preview(b'synthetic actual preview')
        first = client.post('/api/scene'); assert first.status_code == 202
        assert first.json()['preview_sequence'] == 1
        assert client.get('/api/scene').json()['state'] == 'queued'
        assert client.post('/api/scene').json()['request_status'] == 'already_queued'
        assert client.post('/api/llm/query',json={'question':'Describe.','mode':'arbitrary'}).status_code == 422
    manager.stop()


def test_failed_scene_can_retry_same_fresh_snapshot(tmp_db,tmp_path):
    cfg = Settings();cfg.vlm.enabled = True;cfg.evidence.output_dir = str(tmp_path/'images')
    manager = AIManager(cfg,tmp_db)
    def fail(*args,**kwargs):raise RuntimeError('simulated temporary image failure')
    manager.vlm.request = fail
    assert manager.enqueue_scene(b'synthetic image',{'preview_sequence':1})[0] == 'queued'
    manager._thread = threading.Thread(target=manager._worker);manager._thread.start()
    try:
        manager._queue.join()
        assert manager.scene_snapshot()['state'] == 'error'
        assert manager.enqueue_scene(b'synthetic image',{'preview_sequence':1})[0] == 'queued'
    finally:manager.stop()
