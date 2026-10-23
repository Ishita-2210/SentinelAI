"""Simulated transport/model contracts and local publication checks; no hardware."""
import asyncio
from datetime import datetime, timezone
import threading

import pytest

from backend.api import websocket as stream
from backend.schemas.event import Event
from scripts.check_repository import inspect_file


def test_slow_socket_does_not_hold_fast_client_and_is_pruned():
    async def scenario():
        sent = asyncio.Event()

        class Socket:
            def __init__(self, slow=False): self.slow = slow
            async def accept(self): pass
            async def send_text(self, text):
                if self.slow: await asyncio.Event().wait()
                else: sent.set()
            async def close(self, **kwargs): pass

        manager = stream.ConnectionManager()
        manager.send_timeout_s = .03
        slow, fast = Socket(True), Socket()
        await manager.connect(slow)
        await manager.connect(fast)
        task = asyncio.create_task(manager.broadcast({"type":"frame"}))
        await asyncio.wait_for(sent.wait(), .02)
        await task
        assert manager.connection_count == 1
        assert manager._connections == [fast]
    asyncio.run(scenario())


def test_frame_bursts_are_coalesced_and_event_notifications_are_bounded(monkeypatch):
    async def scenario():
        scheduled = []
        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", lambda coroutine, loop: scheduled.append(coroutine))
        stream.set_event_loop(asyncio.get_running_loop())
        try:
            for number in range(10000):
                stream._schedule_broadcast({"type":"frame", "sequence":number})
            for number in range(1000):
                stream._schedule_broadcast({"type":"vlm_result", "id":number})
            assert len(scheduled) == 1
            assert stream._latest_frame["sequence"] == 9999
            assert len(stream._event_updates) == 64
            observed = []
            async def broadcast(payload): observed.append(payload)
            monkeypatch.setattr(stream.manager, "broadcast", broadcast)
            await scheduled.pop()
            assert len(observed) == 65
            assert observed[-1]["sequence"] == 9999
            assert not stream._drain_scheduled
        finally:
            for coroutine in scheduled: coroutine.close()
            stream.set_event_loop(None)
    asyncio.run(scenario())


def test_vlm_processing_state_duration_and_cancellation(tmp_db, tmp_path):
    from backend.ai_runtime.manager import AIManager
    from backend.config.settings import Settings
    from backend.retrival.retrival import EventRetriever
    cfg = Settings(); cfg.vlm.enabled = True
    ai = AIManager(cfg, tmp_db)
    image = tmp_path / 'fixture.jpg'; image.write_bytes(b'simulated image; no real inference')
    ident = tmp_db.save_event(Event('LOITERING', 1, 'person', datetime.now(timezone.utc)), str(image))
    entered, release = threading.Event(), threading.Event()

    def inference(payload, **kwargs):
        entered.set()
        assert release.wait(2)
        return dict(model_id='simulated', answer='unknown', raw_text='simulated caption', adapter_loaded=False)

    ai.vlm.request = inference
    ai.enqueue_event(ident, 'LOITERING', str(image))
    ai._thread = threading.Thread(target=ai._worker)
    ai._thread.start()
    try:
        assert entered.wait(2)
        assert tmp_db.get_event_by_id(ident)['vlm_status'] == 'processing'
        release.set()
        ai._queue.join()
        for record in (EventRetriever(tmp_db).get_by_id(ident), EventRetriever(tmp_db).get_recent()[0]):
            assert record['vlm_status'] == 'inconclusive'
            assert record['vlm_duration_ms'] >= 0
        tmp_db.set_verification(ident, 'processing', 'prompt', 'simulated')
        ai._pending.add(ident)
    finally:
        release.set()
        ai.stop()
    assert tmp_db.get_event_by_id(ident)['vlm_status'] == 'cancelled'


@pytest.mark.parametrize('path,content', [
    ('.env.local', b'anything'),
    ('models/model.pt', b'fixture-model-binary-content'),
    ('data/private.jpg', b'fixture-personal-image-content'),
    ('settings.py', ('TOKEN="ghp_' + 'A' * 36 + '"').encode()),
    ('settings.py', ('password="' + 'aBcDeF0123456789' + '"').encode()),
    ('key.txt', ('-----BEGIN ' + 'PRIVATE KEY-----').encode()),
])
def test_publication_scan_reports_locations_without_secret_values(path, content):
    issues = inspect_file(path, content)
    assert issues
    assert all(isinstance(line, int) and content.decode() not in rule for line, rule in issues)


def test_publication_scan_allows_templates_and_source_assets():
    assert not inspect_file('.env.example', b'password="YOUR_PASSWORD_EXAMPLE"')
    assert not inspect_file('docs/wiring.svg', b'<svg/>')
    assert not inspect_file('tests/fixture.json', b'{"event_type":"LOITERING"}')


def test_staged_scan_checks_index_even_when_working_file_was_sanitized(tmp_path, monkeypatch, capsys):
    import subprocess
    from scripts import check_repository
    subprocess.run(['git','init','--quiet',str(tmp_path)],check=True)
    path = tmp_path / 'settings.py'
    secret = 'ghp_' + 'B' * 36
    path.write_text('TOKEN="' + secret + '"',encoding='utf-8')
    subprocess.run(['git','-C',str(tmp_path),'add','settings.py'],check=True)
    path.write_text('# sanitized working copy',encoding='utf-8')
    monkeypatch.setattr(check_repository,'ROOT',tmp_path)
    assert check_repository.main([]) == 0
    assert check_repository.main(['--staged']) == 1
    output = capsys.readouterr().out
    assert 'settings.py:1: GitHub credential' in output
    assert secret not in output
