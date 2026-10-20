# Accuracy and reliability evaluation

Verified on 20 October 2026 (Asia/Kolkata). Stored event timestamps are UTC. Measurements below distinguish integration, synthetic scenarios and image-question classification.

## Detector and tracker
YOLO11n weights loaded from the existing yolo11n.pt, Ultralytics 8.4.182. Built-in ByteTrack avoids supervision 0.31 API incompatibility. Main calls model.track once per frame; it does not also call Detector.detect. Confidence 0.5, NMS IoU 0.7, CPU on this machine. Coordinates use actual source xyxy pixels and model class names.

An actual 30-frame webcam clip (640x480, encoded at 10 FPS) passed through the host pipeline. The per-frame trace contains a person in 30/30 processed frames with the same track ID 1 and one entry event. This is observed output continuity, not labeled recall or IDF1. Evidence and SQLite records exist. A separate 1280x720 repeated-photo fixture also generated entry and dwell events.

No held-out bounding-box ground truth exists here; precision, recall, F1 and mAP for detection are not reported. No ground-truth identity annotations exist for IDF1/HOTA. A phone was visibly classified as remote in the photo fixture: an identifiable class-confusion limitation. Low light, occlusion, rapid motion and multi-person identity have not been quantitatively evaluated. Processing FPS in browser reports is measured throughput under concurrent workloads, not a guaranteed frame rate.

## Deterministic event scenarios
13 explicit synthetic track sequences contain 23 expected events. Event-count matching per sequence gives TP=23, FP=0, FN=0; precision/recall/F1=1.0 and 0 false positives per sequence. These are software fixture results only. They do not measure real video event accuracy or timing tolerances. Counts by type: entry 12, exit 4, zone change 2, loitering 1, rapid motion 3, unattended object 1.

Negatives include empty sequences, normal motion, temporary track loss, an unassociated object, an owner remaining nearby and a moving object. Raw expectations/predictions are in data/evaluation/events.json. During fixture review two large zone jumps initially lacked RUNNING annotations; their calculated image speeds exceeded the fixed threshold. Those synthetic expectations were corrected and a genuinely slow zone-transition negative was added; this is annotation correction, not an accuracy improvement.

Actual webcam replay exposed false running and dwell accumulation across video rewinds. The fix resets ByteTrack, state and event memory per new source segment. Capture/inference failures also break temporal continuity. Earlier diagnostic database records are preserved; final webcam demonstration uses webcam_final.db. These fixes address observable failure modes without retuning held-out VQA data.

## VQA data integrity
The original 178 records remain unchanged: train 106 (55 yes/46 no/5 unknown), validation 32 (16/14/2), test 40 (24/13/3). SHA-256 manifests are in dataset_audit.json. Scene IDs have no cross-split overlap, but image content does:

| Pair | Shared image hashes |
|---|---:|
| Train / validation | 7 |
| Train / test | 7 |
| Validation / test | 4 |

The 40 test records cover 34 unique image hashes. Seven test records share training images. Excluding test images found in either train or validation leaves 31 records (21 yes/7 no/3 unknown). This is a retrospective read-only subset analysis; it does not repair the original experiment or create a new held-out benchmark. No records were moved, relabeled or used for threshold selection.

## Florence base versus preserved adapter
Both models used identical untouched test questions, the same prompt, greedy generation, four generated tokens, CPU float32, and one model load per evaluation run. Token IDs stay integer; image tensors match model dtype. The Florence implementation constructs its own visual/text attention mask. Raw output and errors are preserved per record, with null numeric confidence.

Main environment Transformers 5.17 failed to load the remote Florence implementation (missing forced_bos_token_id); this failure is recorded separately in data/evaluation/vlm/metrics.json with zero evaluated samples and no fabricated score. Evaluation succeeded using an isolated Transformers 4.49.0, tokenizers 0.21.4, huggingface-hub 0.36.2 and PEFT 0.14.0 overlay. The older PEFT loader warned about newer inactive configuration fields; the original adapter/config were not edited. The runtime remains experimental and disabled by default.

| Evaluation | Base | Adapter | Always yes |
|---|---:|---:|---:|
| Full test, n=40 | 22/40 (55.0%) | 23/40 (57.5%) | 24/40 (60.0%) |
| Non-overlap subset, n=31 | 15/31 (48.4%) | 16/31 (51.6%) | 21/31 (67.7%) |
| UNKNOWN hallucination, full test n=3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) |

The adapter improves only one answer and does not beat the majority baseline. Neither model demonstrates reliable abstention. One sample changes full-test accuracy by 2.5 percentage points; one UNKNOWN case changes its rate by 33.3 points. Repeated images and small supports further limit uncertainty estimates. No significant improvement is claimed.

### Base - full test, n=40

| Gold / prediction | yes | no | unknown |
|---|---:|---:|---:|
| yes | 9 | 14 | 1 |
| no | 0 | 13 | 0 |
| unknown | 2 | 1 | 0 |

| Class | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| yes | 24 | 0.818 | 0.375 | 0.514 |
| no | 13 | 0.464 | 1.000 | 0.634 |
| unknown | 3 | 0.000 | 0.000 | 0.000 |

### Adapter - full test, n=40

| Gold / prediction | yes | no | unknown |
|---|---:|---:|---:|
| yes | 10 | 14 | 0 |
| no | 0 | 13 | 0 |
| unknown | 2 | 1 | 0 |

| Class | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| yes | 24 | 0.833 | 0.417 | 0.556 |
| no | 13 | 0.464 | 1.000 | 0.634 |
| unknown | 3 | 0.000 | 0.000 | 0.000 |

Full and non-overlap per-class metrics/confusion matrices are preserved in vlm_compatible/metrics.json and dataset_audit.json. Most mistakes are false "no" predictions on yes-labelled questions. Both UNKNOWN classes are answered definitively. The single base "unknown" prediction was on a yes-labelled question; that is not successful abstention against this ground truth.

Historical best validation metrics (preserved artifact, not rerun training): 19/32 correct (59.375%), UNKNOWN hallucination 2/2. Do not compare this validation result to test accuracy as a training improvement. Many questions are general VQA rather than surveillance-event evidence, so this dataset cannot validate temporal event verification. Genuine annotated ambiguity and model uncertainty remain distinct; UNKNOWN labels were not manufactured.

Training audit found answer-only decoder targets with padding masked to -100, rather than prompt tokens included as labels. This is a reasonable encoder-decoder objective. The small UNKNOWN support, image leakage, domain mismatch and observed outputs undermine another training run; no model was retrained and the adapter remains preserved.

## Reproduce
```powershell
Set-Location D:\SentinelAI
& .\.venv\Scripts\python.exe scripts/evaluate_events.py
& .\.venv\Scripts\python.exe -m pip install --target data/evaluation/vlm_runtime --no-deps transformers==4.49.0 tokenizers==0.21.4 huggingface-hub==0.36.2 peft==0.14.0
& .\.venv\Scripts\python.exe scripts/run_vlm_compatible.py --output data/evaluation/vlm_compatible
& .\.venv\Scripts\python.exe scripts/audit_dataset.py
```
The VLM run uses cached local model files and offline mode. Install optional torch/transformers-related dependencies from the preserved experiment environment if absent. Re-running can take several minutes on CPU. Core demonstration does not require this overlay.

## Credible next evaluation
Collect independent scene videos with varied lighting, occlusion and motion. Group splits by original image/video content before training; reserve a new unseen test set. Annotate detection boxes, identities and event intervals, including negatives. Select thresholds only on validation. Evaluate detector class precision/recall/mAP, tracking ID switches/IDF1, and event matching by type, identity and a declared timestamp tolerance. Report false positives per hour, misses, confusion matrices, per-class supports and uncertainty. Add genuinely ambiguous VQA examples with independent annotation review before testing abstention again.
