SentinelAI

Event-Driven Edge Intelligence for Real-Time Scene Understanding

SentinelAI is an event-driven computer-vision and AI system designed for real-time scene understanding from a camera endpoint. The project combines lightweight edge sensing with heavier AI inference on a laptop so that the system can reason about what is happening in a scene without sending every frame through a large language or vision-language model.

The core design principle is:

Pixels → Detections → Tracks → States → Events → Evidence → Knowledge → Language

Perception and reasoning are deliberately separated. Deterministic temporal rules are responsible for deciding when an event has occurred, while the VLM is used selectively to verify visual evidence for important events.

1. Project Goals

SentinelAI is being developed to:

Detect people and relevant objects from live camera/video input.

Maintain persistent identities across frames.

Convert frame-level detections into temporal object states.

Detect meaningful events using deterministic rules rather than relying on an LLM to guess events.

Capture visual evidence only when important events occur.

Store events and evidence persistently for later retrieval.

Use a local VLM to verify visual evidence for important events.

Use a local LLM/RAG layer later for natural-language interaction with stored events.

Provide a dashboard and optional hardware alerts through an ESP32 endpoint.

2. High-Level Architecture

                    ┌──────────────────┐
                    │    ESP32-CAM      │
                    │  Camera Endpoint  │
                    └────────┬─────────┘
                             │ video stream
                             ▼
                    ┌──────────────────┐
                    │  Frame Manager   │
                    │     / OpenCV     │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │     YOLO11n      │
                    │ Object Detection │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │    ByteTrack     │
                    │ Object Tracking  │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │  State Manager   │
                    │ Temporal States  │
                    └────────┬─────────┘
                             ▼
                ┌────────────────────────────┐
                │   Event Reasoning Engine   │
                │  Deterministic Rule Logic  │
                └───────┬──────────┬─────────┘
                        │          │
              event     │          │ important event
                        ▼          ▼
              ┌─────────────┐  ┌──────────────┐
              │ SQLite DB   │  │ Keyframe     │
              │ Event Memory│  │ Capture      │
              └──────┬──────┘  └──────┬───────┘
                     │                │
                     │                ▼
                     │        ┌──────────────────┐
                     │        │   Florence-2     │
                     │        │ Fine-tuned VLM   │
                     │        │ Evidence Verify  │
                     │        └────────┬─────────┘
                     │                 │
                     └────────┬────────┘
                              ▼
                     ┌──────────────────┐
                     │ Retrieval / RAG  │
                     └────────┬─────────┘
                              ▼
                     ┌──────────────────┐
                     │   Local LLM      │
                     │ Natural Language │
                     └────────┬─────────┘
                              ▼
               ┌─────────────────────────────┐
               │ Dashboard / API / Alerts   │
               └─────────────────────────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │ ESP32 LED/Buzzer │
                     └──────────────────┘

Architectural principle

The LLM and VLM do not process every frame.

YOLO handles frame-level object detection.

ByteTrack maintains identities over time.

The State Manager maintains temporal object state.

The Event Engine generates events using deterministic rules.

Keyframes are captured only for selected events.

Florence-2 receives important evidence frames and performs focused visual verification.

A local LLM is intended to operate on stored, grounded event information rather than raw video.

This reduces unnecessary multimodal inference and keeps event generation interpretable.

3. Current Technology Stack

Computer Vision

Python

OpenCV

Ultralytics YOLO11n

ByteTrack

Supervision

AI / Multimodal

Florence-2 for visual-language verification

LoRA / PEFT for parameter-efficient fine-tuning

PyTorch

Hugging Face Transformers

Backend / Storage

SQLite

Python backend modules

Development

VS Code

Python virtual environment (.venv)

Git

GitHub

Hardware

ESP32-CAM as the intended sensing/streaming endpoint

ESP32 GPIO output for future LED/buzzer alerts

Planned / Future Components

Local LLM

Retrieval / RAG

Dashboard / API

Optional semantic event search

Optional speech interaction

4. Current Project Status

Completed

Project repository created and connected to GitHub.

Python virtual environment configured.

Requirements environment established.

YOLO11n object detection implemented.

ByteTrack object tracking implemented.

Typed data schemas implemented.

Object State Manager implemented.

Temporal lifecycle handling added for active, missing, and lost objects.

Deterministic Event Reasoning Engine implemented.

Zone representation implemented.

Person entry/exit logic implemented.

Zone transition logic implemented.

Loitering detection implemented.

Running detection implemented.

Person-object association implemented.

Unattended-object detection implemented.

Event persistence implemented using SQLite.

Event history viewer implemented.

Keyframe evidence capture implemented.

Evidence paths stored with events.

Florence-2 successfully loaded and tested locally on CPU.

Initial Florence-2 visual captioning test completed.

Currently In Progress

SentinelAI-specific VLM dataset creation.

Florence-2 LoRA fine-tuning design.

Hallucination-resistant YES/NO/UNKNOWN training formulation.

Held-out VLM evaluation.

Planned

Complete VLM fine-tuning on a GPU environment.

Compare base Florence-2 against the fine-tuned adapter.

Integrate VLM verification into the event pipeline.

Add retrieval / RAG over event memory.

Integrate a local LLM for natural-language event queries.

Build the monitoring dashboard.

Add ESP32-CAM streaming.

Add ESP32 LED/buzzer alerts.

Add end-to-end testing and performance measurement.

5. Implemented Computer Vision Pipeline

Detection

The detector uses YOLO11n and converts model results into typed Detection objects containing:

Class ID

Class name

Confidence

Bounding box

Tracking

ByteTrack converts frame-level detections into persistent tracks with track IDs.

Each track contains:

Track ID

Class ID

Class name

Confidence

Bounding box

State Management

The State Manager converts tracks into temporal ObjectState objects.

State information includes:

Current bounding box

Previous bounding box

First seen timestamp

Last seen timestamp

Position history

Velocity

Current zone

Lifecycle status

Missing timestamp

Zone entry timestamp

Loitering state

Running state

Unattended state

Object lifecycle states currently include:

ACTIVE → MISSING → LOST

6. Event Reasoning Engine

SentinelAI intentionally uses deterministic event logic instead of asking a generative model to infer events directly from individual frames.

Current events

Person Entry

A person entering a configured zone generates:

PERSON_ENTERED

Person Exit

A person leaving the zone generates:

PERSON_EXITED

Zone Transition

Movement between zones generates:

ZONE_CHANGED

Loitering

If a person remains in a zone beyond the configured dwell-time threshold:

LOITERING

Current threshold:

10 seconds

Running

If tracked displacement exceeds the configured velocity threshold:

RUNNING

Unattended Object

The current unattended-object reasoning associates an object with a nearby person, detects sustained separation, checks whether the object remains stationary, and then generates:

UNATTENDED_OBJECT

Current important parameters include:

Association distance: 350 px
Separation distance: 250 px
Unattended threshold: 5 seconds

The unattended-object logic has been tested successfully in the current pipeline.

7. Event Memory and Evidence

SentinelAI stores detected events in SQLite.

The event table currently records:

Event ID

Event type

Track ID

Object class

Timestamp

Zone

Confidence

Description

Evidence path

Example event flow:

Event detected
      ↓
Keyframe captured
      ↓
Event stored in SQLite
      ↓
Evidence path stored with event

The event database also supports retrieving recent events, filtering by event type, and counting events.

A command-line event history viewer is available through view_events.py.

8. Keyframe Evidence Capture

The evidence module stores selected frames under:

D:\SentinelAI\data\events\

Keyframes are currently captured for important events such as:

LOITERING
UNATTENDED_OBJECT

The filename records timestamp, event type, and track ID.

Example pattern:

YYYYMMDD_HHMMSS_mmm_EVENTTYPE_track_ID.jpg

This creates a persistent visual evidence trail for event verification and future retrieval.

9. VLM Component

Current model

The current VLM direction is based on:

microsoft/Florence-2-base

The fine-tuning target is:

microsoft/Florence-2-base-ft

Florence-2 has been successfully loaded locally on CPU in the current environment.

Why Florence-2?

The project needs a relatively lightweight multimodal model that can provide useful visual information while leaving the main temporal event reasoning to the deterministic backend.

The first Florence test showed significantly richer visual descriptions than the initial SmolVLM experiment, although the output also demonstrated the need for task-specific constraints and fine-tuning because some details can be inconsistent or unsupported.

VLM responsibility

The VLM should answer focused visual verification questions such as:

Is the person visibly holding the object?
Is the object visible?
Are the person and object visibly separated?
Is the person visibly sitting?
Is the person visibly running?

It should not independently decide temporal events such as UNATTENDED_OBJECT from one frame.

10. Hallucination-Reduction Strategy

The fine-tuned VLM is being designed as a conservative visual evidence verifier.

The target output uses three primary decision states:

YES
NO
UNKNOWN

Examples:

YES: The person is visibly holding the bottle.

NO: The person is not visibly holding the bottle.

UNKNOWN: Ownership cannot be determined from the image alone.

The dataset intentionally includes:

Positive cases

Negative cases

Hard negatives

Ambiguous scenes

Occluded scenes

Insufficient-evidence cases

The aim is to reduce unsupported claims rather than simply increase model confidence.

11. VLM Fine-Tuning Plan

The current fine-tuning approach is:

Florence-2-base-ft
        ↓
Freeze vision encoder
        ↓
LoRA / PEFT
        ↓
SentinelAI visual verification dataset
        ↓
GPU fine-tuning
        ↓
Saved LoRA adapter
        ↓
CPU inference on laptop

Initial training configuration

The current planned configuration uses:

LoRA rank: 8
LoRA alpha: 16
LoRA dropout: 0.05
Learning rate: 1e-6
Batch size: 1
Gradient accumulation: 8

The training implementation is designed to include validation loss and early stopping.

12. VLM Dataset Design

The dataset is organized as:

D:\SentinelAI\dataset\
├── README.md
├── images\
├── train.jsonl
├── val.jsonl
└── test.jsonl

Each JSONL record contains:

{
  "image": "scene_001.jpg",
  "detected_objects": ["person", "bottle"],
  "question": "Is the person visibly holding the bottle?",
  "answer": "YES: The person is visibly holding the bottle."
}

The dataset should contain multiple different scenes rather than repeatedly using a single image.

The current backend/event/test.jpg is being kept as a test/example image and should not be duplicated across training and test splits.

Recommended dataset categories include:

Object visibility
Person visibility
Holding / touching
Near / separated
Standing / sitting / running
Ambiguous visual relationships
Insufficient evidence

For video-derived data, train/validation/test splits should preferably be performed by recording or scene rather than by randomly splitting adjacent frames.

13. Evaluation Plan

The fine-tuned model will be evaluated on a held-out test set that is not used during training.

The evaluation will compare:

Florence-2-base-ft
        VS
Florence-2-base-ft + SentinelAI LoRA

Metrics will include:

Overall classification accuracy

YES accuracy

NO accuracy

UNKNOWN accuracy

Unsupported YES/NO responses on UNKNOWN cases

Manual evidence-faithfulness review

The goal is to measure whether fine-tuning actually improves reliable visual verification and reduces unsupported claims.

14. Repository Structure

Current and planned structure:

SentinelAI/
│
├── backend/
│   ├── api/
│   ├── camera/
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── core/
│   ├── database/
│   │   ├── __init__.py
│   │   ├── event_database.py
│   │   └── view_events.py
│   ├── detector/
│   │   └── detector.py
│   ├── event_engine/
│   │   ├── zone.py
│   │   └── event_engine.py
│   ├── evidence/
│   │   ├── __init__.py
│   │   └── keyframe_capture.py
│   ├── llm/
│   ├── retrieval/
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── bounding_box.py
│   │   ├── detection.py
│   │   ├── frame.py
│   │   ├── track.py
│   │   ├── object_state.py
│   │   └── event.py
│   ├── services/
│   ├── state_manager/
│   │   └── state_manager.py
│   ├── tracker/
│   │   └── tracker.py
│   ├── utils/
│   ├── vlm/
│   │   ├── __init__.py
│   │   ├── vlm.py
│   │   └── test_vlm.py
│   └── main.py
│
├── dataset/
│   ├── README.md
│   ├── images/
│   ├── train.jsonl
│   ├── val.jsonl
│   └── test.jsonl
│
├── training/
│   └── future training scripts / experiments
│
├── models/
│   └── trained adapters and model artifacts
│
├── data/
│   ├── events/
│   └── sentinelai.db
│
├── requirements.txt
├── .gitignore
└── README.md

Note: Some folders are planned and may still be empty while the corresponding modules are being developed.

15. Running the Current System

Activate the virtual environment:

cd D:\SentinelAI
.\.venv\Scripts\Activate.ps1

Run the main vision/event pipeline

python -m backend.main

View stored events

python -m backend.database.view_events

Test Florence-2

python -m backend.vlm.test_vlm

The current Florence test uses:

D:\SentinelAI\backend\event\test.jpg

16. Environment Notes

The project currently uses a Windows Python virtual environment:

D:\SentinelAI\.venv

The active environment should be kept consistent rather than mixing packages between Conda and .venv.

Important packages currently used include:

torch
transformers
ultralytics
supervision
opencv-python
pillow
peft
timm
einops

Florence-2 requires additional vision-related dependencies such as timm and einops for its remote implementation.

17. Git / Repository Hygiene

Large model weights should not be committed to Git.

Examples already excluded from version control include:

*.pt
data/*.db
data/events/

Generated datasets, model adapters, and large binary artifacts should be handled deliberately rather than committed blindly.

18. Development Milestones

Milestone 1 — Architecture

Defined event-driven architecture.

Separated perception, tracking, state, events, VLM, memory, and language layers.

Milestone 2 — Perception

YOLO11n detector implemented.

ByteTrack tracker implemented.

Structured detection and tracking schemas created.

Milestone 3 — Temporal State

Object State Manager implemented.

Position history and velocity implemented.

Missing/lost lifecycle added.

Milestone 4 — Event Reasoning

Zones implemented.

Entry/exit implemented.

Loitering implemented.

Running implemented.

Person-object association implemented.

Unattended-object reasoning validated.

Milestone 5 — Persistent Memory

SQLite event database implemented.

Event history viewer implemented.

Keyframe evidence capture implemented.

Milestone 6 — Multimodal Verification

Initial VLM experiments completed.

Florence-2 selected as the current VLM direction.

Local CPU inference confirmed.

Milestone 7 — VLM Specialization

SentinelAI VLM dataset design completed.

LoRA fine-tuning pipeline being prepared.

Held-out evaluation methodology defined.

Future Milestones

RAG / event retrieval

Local LLM

Dashboard

ESP32-CAM integration

Hardware alerts

End-to-end optimization

Performance benchmarking

19. Design Philosophy

SentinelAI follows several principles:

Deterministic event generation

Important events should emerge from explicit temporal rules and measurable state rather than unconstrained generative guesses.

Evidence before language

Visual evidence is captured and stored before a language model is asked to explain an event.

Event-driven multimodal inference

The VLM is not used on every frame. It is triggered selectively for important events.

Conservative visual reasoning

When the image does not provide enough evidence, the VLM should prefer UNKNOWN rather than inventing an answer.

Persistent memory

Events should remain queryable after the original video frame has passed.

Edge-aware deployment

The intended endpoint is lightweight camera hardware, while computationally heavy inference is currently performed on the laptop.

20. Current Project State

Overall: Core perception, tracking, temporal state management, deterministic event reasoning, event persistence, evidence capture, and initial VLM integration are implemented.

Current focus: Build and train a SentinelAI-specific Florence-2 visual verifier, then measure whether the fine-tuned model improves accuracy and reduces unsupported visual claims on unseen scenes.

Next major integration:

Event Engine
     ↓
Keyframe Capture
     ↓
Fine-tuned Florence-2
     ↓
Verified visual evidence
     ↓
SQLite Event Memory
     ↓
RAG / Local LLM
     ↓
Dashboard + Alerts

License

This repository is currently a project/research development repository. Add the final license and attribution information before public release.
