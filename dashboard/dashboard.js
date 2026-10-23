'use strict';
const API = location.origin + '/api';
const WS = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/stream`;
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const label = value => String(value ?? 'unknown').replace(/_/g, ' ');
const validId = value => Number.isSafeInteger(Number(value)) && Number(value) > 0;
const evidenceURL = path => '/evidence/' + encodeURIComponent(String(path).split(/[\\/]/).pop());
const timeLabel = value => { const d = new Date(value); return Number.isFinite(d.getTime()) ? d.toLocaleString() : 'Time unavailable'; };
const duration = value => value == null ? 'Not measured' : (Number(value) / 1000).toFixed(2) + ' s';
const tone = state => ['ready','live','connected'].includes(state) ? 'ok' : ['error','disconnected','unavailable'].includes(state) ? 'err' : 'warn';
let allEvents = [], activeFilter = '', eventsKey = '', ws, reconnectTimer, wsDelay = 1000, stopped = false;
let healthBusy = false, eventsBusy = false, previewBusy = false, previewObjectURL, lastPreviewOK = 0;
let selectedId = null, detailKey = '', detailBusy = false, detailVersion = 0, lastFocus;
let scenePollBusy = false, sceneSubmitting = false, sceneActive = false, lastSceneAttempt = 0, displayedSceneId;
const timers = [];

async function request(url, options = {}, timeout = 5000) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {...options, signal:controller.signal, cache:'no-store'});
    if (!response.ok) {
      let message = 'HTTP ' + response.status;
      try { const data = await response.json(); if (typeof data.detail === 'string') message = data.detail; } catch {}
      throw new Error(message);
    }
    return await response.json();
  } finally { clearTimeout(timer); }
}

function setPill(id, state, text) { $(id).className = 'pill ' + state; $(id).textContent = text; $(id).title = text; }
function hidePreview(reason) {
  $('live-preview').hidden = true; $('cam-placeholder').hidden = false;
  $('preview-message').textContent = reason; setPill('pill-cam','warn','Camera · waiting'); $('pill-cam').title = reason;
}
function renderTracks(tracks = []) {
  $('tracks-chip').textContent = tracks.length;
  $('track-chip').textContent = tracks.length + ' tracks';
  const list = $('track-list'), retained = new Set(tracks.map(t => String(t.track_id)));
  list.querySelectorAll('[data-track-id]').forEach(row => { if (!retained.has(row.dataset.trackId)) row.remove(); });
  let empty = list.querySelector('.empty');
  if (tracks.length && empty) empty.remove();
  if (!tracks.length && !empty) { empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'No active tracks in the latest frame'; list.append(empty); }
  const rows = new Map([...list.querySelectorAll('[data-track-id]')].map(row => [row.dataset.trackId,row]));
  for (const track of tracks) {
    let row = rows.get(String(track.track_id));
    if (!row) { row = document.createElement('div'); row.className = 'track-item'; row.dataset.trackId = String(track.track_id); list.append(row); }
    const content = `<span><span class="tid">#${esc(track.track_id)}</span> ${esc(track.class_name)}<br><span class="tzone">${esc(track.zone || 'No named zone')}</span></span><span class="tconf">${Number.isFinite(track.confidence) ? (track.confidence * 100).toFixed(0) + '% detection' : 'Confidence unavailable'}</span>`;
    if (row.innerHTML !== content) row.innerHTML = content;
  }
}

function renderScene(data) {
  sceneActive = ['queued','describing','explaining'].includes(data.state);
  $('describe-scene').disabled = sceneActive || sceneSubmitting;
  $('describe-scene').textContent = sceneActive ? 'Analyzing snapshot…' : 'Describe current frame';
  if (data.caption) {
    if (displayedSceneId !== data.id) {
      displayedSceneId = data.id;
      $('scene-caption').textContent = data.caption;
      $('scene-explanation').textContent = 'Writing an explanation of this image description…';
      $('scene-source').textContent = `${data.source_label || data.source_kind || 'Source'} · Snapshot ${timeLabel(data.requested_at)} · annotated frame #${data.preview_sequence}`;
      $('scene-evidence').href = evidenceURL(data.evidence_url); $('scene-evidence').hidden = false;
    }
    if (data.explanation) $('scene-explanation').textContent = data.explanation;
    $('scene-explanation-detail').textContent = [data.explanation_model || 'Local LLM', label(data.explanation_status), data.llm_used ? 'Written model interpretation' : data.explanation ? 'Visual-description fallback; LLM not used' : '', data.explanation_ms == null ? '' : duration(data.explanation_ms), data.explanation_error].filter(Boolean).join(' · ');
  }
  const messages = {idle:'Ready to describe a fresh source frame.', queued:'Snapshot saved; waiting for the current inference to finish.', describing:'Florence is writing a description of the saved frame.', explaining:'Visual description ready. The local LLM is writing its explanation.', completed:'Saved-frame description and interpretation. Check the original frame; model observations may be inaccurate.', error:'Could not describe this snapshot: ' + (data.error || 'Model error'), cancelled:'Analysis was cancelled. Request a fresh snapshot after restarting.', unavailable:'Start the video pipeline with VLM enabled to describe a frame.'};
  $('scene-status').textContent = (messages[data.state] || label(data.state)) + (sceneActive && displayedSceneId && !data.caption ? ' Previous completed description remains visible until the new one is ready.' : '');
}
async function pollScene() {
  if (scenePollBusy || stopped) return;
  scenePollBusy = true;
  try { renderScene(await request(API + '/scene')); }
  catch (error) { $('scene-status').textContent = 'Scene analysis status unavailable: ' + error.message + '. Any displayed text refers to its saved snapshot.'; }
  finally { scenePollBusy = false; }
}
async function describeScene() {
  if (sceneSubmitting || sceneActive || stopped) return;
  sceneSubmitting = true; lastSceneAttempt = Date.now(); $('describe-scene').disabled = true;
  $('scene-status').textContent = 'Saving the actual current frame for description…';
  try { renderScene(await request(API + '/scene',{method:'POST'})); }
  catch (error) { $('scene-status').textContent = error.message + '. Previous descriptions, if any, refer to their saved snapshots.'; }
  finally { sceneSubmitting = false; $('describe-scene').disabled = sceneActive; }
}
$('describe-scene').addEventListener('click',describeScene);
function visualStatus(event) {
  if (event.vlm_error) return 'Visual check failed: ' + event.vlm_error;
  if (event.vlm_status === 'inconclusive') return event.vlm_task === '<DETAILED_CAPTION>' ? 'Caption available · interpretation remains inconclusive' : 'Presence hypothesis: ' + (event.vlm_answer || 'unknown') + ' · uncalibrated';
  return 'Visual check: ' + label(event.vlm_status || 'not requested');
}
function renderEvents() {
  const items = activeFilter ? allEvents.filter(e => e.event_type === activeFilter) : allEvents;
  $('ev-chip').textContent = items.length;
  $('event-list').innerHTML = items.length ? items.map(ev => `<article class="ev" data-evid="${Number(ev.id)}"><div class="ev-row1"><span class="ev-badge ${['PERSON_ENTERED','PERSON_EXITED','ZONE_CHANGED','LOITERING','RUNNING','UNATTENDED_OBJECT'].includes(ev.event_type) ? 'b-' + ev.event_type : ''}">${esc(label(ev.event_type))}</span><time class="ev-time" datetime="${esc(ev.timestamp)}">${esc(timeLabel(ev.timestamp))}</time></div><p class="ev-desc">Track #${esc(ev.track_id)} · ${esc(ev.zone || 'No named zone')}<br>${esc(ev.description)}</p><p class="ev-vlm">${esc(visualStatus(ev))}</p><div class="ev-actions"><button class="fb inspect-event" data-id="${Number(ev.id)}">Inspect event #${Number(ev.id)} →</button><span class="ev-vlm">${esc((ev.source_metadata || {}).source_label || (ev.source_metadata || {}).source_kind || 'Source not recorded')}</span></div></article>`).join('') : '<p class="empty">' + (activeFilter ? 'No recent events match this filter.' : 'No saved events yet. Events appear when the source and rule conditions produce them.') + '</p>';
}
function renderEvidence() {
  const images = allEvents.filter(e => e.evidence_path).slice(0,24);
  $('ev-count-chip').textContent = images.length;
  $('ev-grid').innerHTML = images.length ? images.map(ev => `<button class="ev-thumb inspect-event" data-id="${Number(ev.id)}" aria-label="Inspect evidence for event ${Number(ev.id)}"><img src="${esc(evidenceURL(ev.evidence_path))}" alt="Saved keyframe for event ${Number(ev.id)}" loading="lazy"><span>#${Number(ev.id)} · ${esc(label(ev.event_type))}</span></button>`).join('') : '<p class="empty">No saved keyframes in recent history</p>';
  $('ev-grid').querySelectorAll('img').forEach(image => image.addEventListener('error', () => { image.hidden = true; image.nextElementSibling.textContent += ' · image unavailable'; }, {once:true}));
}
async function loadInitial() {
  if (eventsBusy || stopped) return;
  eventsBusy = true;
  try {
    const [data, stats] = await Promise.all([request(API + '/events?limit=120'), request(API + '/stats')]);
    const next = [...new Map(data.events.filter(e => validId(e.id)).map(e => [Number(e.id),e])).values()];
    const key = JSON.stringify(next);
    if (key !== eventsKey) { allEvents = next; eventsKey = key; renderEvents(); renderEvidence(); }
    $('st-total').textContent = stats.total;
    $('events-status').textContent = `Showing ${allEvents.length} recent records. Rule labels do not establish identity or intent.`;
  } catch (error) { $('events-status').textContent = 'Event history could not refresh: ' + error.message + '. Retaining the last loaded records.'; }
  finally { eventsBusy = false; }
}
function modelSummary(model) {
  return [model.model_id || 'Not configured', model.busy ? 'Inference in progress' : label(model.state), 'Completed: ' + (model.inference_count || 0), model.last_inference_ms == null ? null : 'Last inference: ' + duration(model.last_inference_ms), model.queued == null ? null : 'Queued: ' + model.queued, model.error, model.last_inference_error, model.adapter_warning].filter(Boolean).join(' · ');
}
async function pollHealth() {
  if (healthBusy || stopped) return;
  healthBusy = true;
  try {
    const data = await request(API + '/health');
    $('api-state').textContent = label(data.status);
    $('api-state').className = 'chip ' + tone(data.status === 'ok' ? 'ready' : data.status);
    $('fps-val').textContent = Number(data.fps || 0).toFixed(1);
    $('frame-age').textContent = 'Age: ' + (data.preview_age_s == null ? 'unavailable' : Number(data.preview_age_s).toFixed(1) + ' s');
    $('st-tracks').textContent = data.track_count || 0;
    if (!data.frames_arriving) { hidePreview(data.preview_status === 'stale' ? 'Frames paused / stale' : data.camera_status || 'Waiting for frames'); renderTracks(); }
    $('device-status').textContent = 'Source: ' + (data.source_label || data.source_kind || 'API / history only') + ' · ' + (data.source || '') + ' · ESP32 telemetry: ' + (data.esp32_status || 'disabled') + ' · ESP32 camera: ' + (data.esp32_camera_verified ? 'live frame provenance received; physical validation requires review' : 'physically unverified');
    const models = data.models || {}, vm = models.vlm || {state:'disabled'}, lm = models.llm || {state:'disabled'};
    setPill('pill-vlm',tone(vm.state),'VLM · ' + (vm.busy ? 'processing' : vm.state));
    setPill('pill-llm',tone(lm.state),'LLM · ' + (lm.busy ? 'processing' : lm.state));
    $('st-vlm').textContent = vm.busy ? 'Processing' : label(vm.state);
    $('st-vlm-sub').textContent = 'Completed: ' + (vm.inference_count || 0) + ' · Queued: ' + (vm.queued || 0);
    $('vlm-detail').textContent = modelSummary(vm);
    $('llm-detail').textContent = modelSummary(lm);
    if ($('auto-describe').checked && data.frames_arriving && vm.state === 'ready' && Date.now() - lastSceneAttempt >= 30000 && !sceneActive) describeScene();
    const components = [['Source',data.camera_status],['Detector',data.yolo_status],['Tracker',data.tracker_status],['Event rules',data.event_engine_status],['SQLite',data.database_status],['REST API','ready']];
    $('component-status').innerHTML = components.map(([name,state]) => `<div class="health-item"><span>${esc(name)}</span><span class="${tone(state)}">${esc(label(state))}</span></div>`).join('') + (data.last_error ? '<p class="health-note">' + esc(data.last_error) + '</p>' : '');
    $('footer-ts').textContent = 'Status checked ' + new Date().toLocaleTimeString();
  } catch (error) {
    $('api-state').textContent = 'Unavailable'; $('api-state').className = 'chip err';
    $('component-status').textContent = 'API unreachable. Previously displayed model and source states are stale.';
    $('vlm-detail').textContent = $('llm-detail').textContent = 'Runtime state unavailable until the API reconnects.';
    $('st-vlm').textContent = 'Unavailable'; $('st-vlm-sub').textContent = 'API status is stale';
    $('device-status').textContent = 'Source status unavailable. ESP32 camera remains physically unverified.';
    $('fps-val').textContent = '—'; $('st-tracks').textContent = '—'; renderTracks();
    hidePreview('API unavailable'); setPill('pill-vlm','err','VLM · unknown'); setPill('pill-llm','err','LLM · unknown');
    $('footer-ts').textContent = 'Status refresh failed: ' + error.message;
  } finally { healthBusy = false; }
}
function connectWS() {
  if (stopped) return;
  setPill('pill-ws','warn','Stream · connecting');
  ws = new WebSocket(WS);
  ws.onopen = () => { setPill('pill-ws','ok','Stream · connected'); wsDelay = 1000; $('dc-banner').classList.remove('show'); };
  ws.onmessage = event => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'frame') { renderTracks(data.tracks || []); $('hud-ts').textContent = timeLabel(data.timestamp); if ((data.events || []).length) loadInitial(); }
      if (data.type === 'vlm_result') { loadInitial(); refreshDetail(); }
    } catch { $('events-status').textContent = 'Unreadable stream update; event history will refresh through the API.'; }
  };
  ws.onclose = () => { if (stopped) return; setPill('pill-ws','warn','Stream · retrying'); $('dc-banner').classList.add('show'); reconnectTimer = setTimeout(connectWS,wsDelay); wsDelay = Math.min(wsDelay * 1.5,15000); };
  ws.onerror = () => ws.close();
}
async function refreshPreview() {
  if (previewBusy || stopped) return;
  previewBusy = true;
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(),4000);
  try {
    const response = await fetch(API + '/frame.jpg?t=' + Date.now(),{cache:'no-store',signal:controller.signal});
    if (!response.ok) throw new Error('No fresh preview');
    const nextURL = URL.createObjectURL(await response.blob()), image = $('live-preview');
    try { image.src = nextURL; await image.decode(); } catch (error) { URL.revokeObjectURL(nextURL); throw error; }
    if (previewObjectURL) URL.revokeObjectURL(previewObjectURL);
    previewObjectURL = nextURL; lastPreviewOK = Date.now();
    image.hidden = false; $('cam-placeholder').hidden = true; setPill('pill-cam','ok','Camera · live');
  } catch { hidePreview('Waiting for fresh frames'); }
  finally { clearTimeout(timer); previewBusy = false; }
}
function detailHTML(ev) {
  const metadata = ev.source_metadata || {}, row = (name,value) => `<dt>${esc(name)}</dt><dd>${esc(value ?? 'Not recorded')}</dd>`;
  const output = ev.vlm_error || ev.vlm_raw_text || 'No model output recorded for this evidence.';
  const busy = ['queued','processing'].includes(ev.vlm_status);
  return `<section><h3>Original event evidence</h3>${ev.evidence_path ? `<img id="detail-image" src="${esc(evidenceURL(ev.evidence_path))}" alt="Original saved keyframe for event ${Number(ev.id)}"><p class="panel-note" id="image-status">Saved evidence · loading dimensions…</p>` : '<p class="empty">This event has no saved image reference.</p>'}<dl>${row('Timestamp',timeLabel(ev.timestamp))}${row('Source',metadata.source_label || metadata.source_kind)}${row('Received',metadata.received_at)}${row('Frame',metadata.sequence ?? metadata.frame_index)}${row('Evidence hash',ev.vlm_evidence_sha256)}</dl><h3>Observed workflow</h3><div class="stage-list"><span class="complete">Event stored</span><span class="${ev.evidence_path ? 'complete' : ''}">${ev.evidence_path ? 'Image reference saved' : 'No image reference'}</span><span>VLM: ${esc(label(ev.vlm_status || 'not requested'))}</span><span>LLM: on request</span></div><p class="panel-note">These stages reflect saved records. A file reference alone does not establish image availability or the accuracy of a model result.</p></section><section><h3>Deterministic event rule</h3><p class="muted">${esc(ev.description || label(ev.event_type))}</p><dl>${row('Event',label(ev.event_type))}${row('Track',ev.track_id)}${row('Object',ev.class_name)}${row('Zone',ev.zone)}</dl><h3>Florence-2 visual analysis</h3><p class="panel-note">${esc(visualStatus(ev))}</p><dl>${row('Model',ev.vlm_model_id)}${row('Task',ev.vlm_task)}${row('Prompt',ev.vlm_prompt)}${row('Updated',ev.vlm_checked_at ? timeLabel(ev.vlm_checked_at) : null)}${row('Processing',duration(ev.vlm_duration_ms))}</dl><div class="observation">${esc(output)}</div><p class="panel-note">${esc(ev.vlm_scope || 'Still-image observation only. Temporal rule, identity and intent are not verified by this result.')} Processing duration includes waiting for model readiness when applicable.</p><div class="ev-actions"><button class="fb" id="detail-verify" ${!ev.evidence_path || busy ? 'disabled' : ''}>${busy ? esc(label(ev.vlm_status)) : 'Analyze saved keyframe'}</button><button class="fb" id="detail-ask">Ask about event #${Number(ev.id)}</button><a href="/api/events/${Number(ev.id)}" target="_blank" rel="noopener">Original record ↗</a></div><p id="detail-status" role="status" class="panel-note"></p></section>`;
}
async function refreshDetail() {
  if (!selectedId || detailBusy || stopped) return;
  detailBusy = true;
  const id = selectedId, version = detailVersion;
  try {
    const ev = await request(API + '/events/' + id);
    if (id !== selectedId || version !== detailVersion) return;
    const key = JSON.stringify(ev);
    if (key === detailKey) return;
    detailKey = key; $('detail-title').textContent = 'Event #' + ev.id + ' · ' + label(ev.event_type);
    const focused = document.activeElement?.id;
    $('detail-content').innerHTML = detailHTML(ev);
    const image = $('detail-image');
    if (image) { image.onload = () => { $('image-status').textContent = `Original keyframe · ${image.naturalWidth} × ${image.naturalHeight} px`; }; image.onerror = () => { image.hidden = true; $('image-status').textContent = 'Saved image is unavailable. Its record is preserved.'; }; }
    $('detail-verify').onclick = async () => {
      const button = $('detail-verify'); button.disabled = true; $('detail-status').textContent = 'Requesting analysis of this saved evidence…';
      try { const data = await request(API + '/events/' + id + '/verify',{method:'POST'}); if (id === selectedId) { $('detail-status').textContent = label(data.verification_status); detailKey = ''; refreshDetail(); loadInitial(); } }
      catch (error) { if (id === selectedId) { $('detail-status').textContent = error.message + '. Correct the model or evidence problem, then retry.'; button.disabled = false; } }
    };
    $('detail-ask').onclick = () => { closeDetail(); $('qa-question').value = 'Show event #' + id; $('qa-question').focus(); };
    if (focused && $(focused)) $(focused).focus();
  } catch (error) { if (id === selectedId && version === detailVersion) { const notice = $('detail-status'); if (notice) notice.textContent = 'Unable to refresh this event: ' + error.message; else $('detail-content').textContent = 'Unable to load event: ' + error.message; } }
  finally { detailBusy = false; }
}
function openDetail(id) {
  if (!validId(id)) return;
  selectedId = Number(id); detailVersion++; detailKey = ''; lastFocus = document.activeElement;
  $('detail-title').textContent = 'Event #' + selectedId; $('detail-content').textContent = 'Loading event and evidence…';
  if (!$('event-dialog').open) $('event-dialog').showModal();
  refreshDetail();
}
function closeDetail() { $('event-dialog').close(); }
$('event-dialog').addEventListener('close', () => { selectedId = null; detailVersion++; if (lastFocus?.isConnected) lastFocus.focus(); });
$('detail-close').addEventListener('click',closeDetail);
document.addEventListener('click',event => { const button = event.target.closest('.inspect-event'); if (button) openDetail(button.dataset.id); });
$('filter-bar').addEventListener('click',event => {
  const button = event.target.closest('[data-type]'); if (!button) return;
  activeFilter = button.dataset.type;
  $('filter-bar').querySelectorAll('button').forEach(b => { b.classList.toggle('active',b === button); b.setAttribute('aria-pressed',String(b === button)); }); renderEvents();
});
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => { $('qa-question').value = button.dataset.question; $('qa-question').focus(); }));
$('qa-form').addEventListener('submit',async event => {
  event.preventDefault(); const question = $('qa-question').value.trim(); if (!question) return;
  $('qa-submit').disabled = true; $('qa-answer').textContent = ''; $('qa-sources').replaceChildren();
  $('qa-status').textContent = 'Retrieving event evidence and requesting local inference…';
  try {
    const data = await request(API + '/llm/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,limit:20,mode:$('qa-mode').value})},60000);
    $('qa-status').textContent = `Task: ${question} · ${data.model || 'Model not configured'} · ${label(data.generation_status)} · ${data.answer_kind === 'model_explanation' ? 'Written AI interpretation' : data.llm_used ? 'Recorded facts with model-selected sources' : 'Supplied-data fallback'}${data.inference_ms == null ? '' : ' · Inference: ' + duration(data.inference_ms)}${data.notice ? ' · ' + data.notice : ''}${data.error ? ' · ' + data.error : ''}`;
    $('qa-answer').textContent = data.answer;
    for (const source of data.sources || []) {
      if (!validId(source.id)) continue;
      const li = document.createElement('li'), button = document.createElement('button');
      button.type = 'button'; button.className = 'fb inspect-event'; button.dataset.id = source.id;
      button.textContent = 'Event #' + source.id + ' · ' + label(source.event_type); li.append(button);
      if (source.evidence_path) { const link = document.createElement('a'); link.href = evidenceURL(source.evidence_path); link.textContent = ' · Keyframe ↗'; link.target = '_blank'; link.rel = 'noopener'; li.append(link); }
      $('qa-sources').append(li);
    }
  } catch (error) { $('qa-status').textContent = error.name === 'AbortError' ? 'Local question timed out. Monitoring continues; retry when the model is available.' : error.message + '. You can retry this question.'; }
  finally { $('qa-submit').disabled = false; pollHealth(); }
});
timers.push(setInterval(refreshPreview,500),setInterval(pollHealth,3000),setInterval(loadInitial,3000),setInterval(refreshDetail,2000),setInterval(pollScene,2000),setInterval(() => { if (Date.now() - lastPreviewOK > 5000) hidePreview('Frames paused / stale'); },1000));
window.addEventListener('pagehide', () => { stopped = true; timers.forEach(clearInterval); clearTimeout(reconnectTimer); if (ws) ws.close(); if (previewObjectURL) URL.revokeObjectURL(previewObjectURL); });
refreshPreview(); connectWS(); pollHealth(); loadInitial(); pollScene();
