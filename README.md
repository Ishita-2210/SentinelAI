# SentinelAI

### Event-Driven Edge Intelligence for Real-Time Scene Understanding

SentinelAI is a real-time scene understanding system that combines computer vision, temporal reasoning, and multimodal AI to detect meaningful events from live camera streams.

The system is designed around a simple idea:

> **Do not make AI reason about every frame. First understand what is happening, then invoke deeper AI only when it matters.**

---

## Architecture

```text
Camera / ESP32-CAM
        ↓
Frame Capture
        ↓
YOLO11n
        ↓
Object Detection
        ↓
ByteTrack
        ↓
Object Tracking
        ↓
Object State Manager
        ↓
Event Reasoning Engine
        ↓
   ┌────┼────┐
   ↓    ↓    ↓
SQLite  Evidence  Alerts
        Capture
          ↓
     Florence-2 VLM
          ↓
 Visual Verification
          ↓
   Persistent Memory
          ↓
     Retrieval / RAG
          ↓
      Local LLM
          ↓
     Dashboard / API
          ↓
      ESP32 Actions
```

---

## What Has Been Built

### Object Detection

YOLO11n has been integrated for real-time object detection.

Each detection contains:

* Class ID
* Class name
* Confidence
* Bounding box

### Object Tracking

ByteTrack has been integrated to maintain persistent object identities across frames.

```text
Frame 1 → Person → ID 1
Frame 2 → Person → ID 1
Frame 3 → Person → ID 1
```

### Object State Management

The State Manager maintains temporal information for tracked objects, including:

* Position history
* Velocity
* First/last seen timestamps
* Zone
* Missing/lost status
* Dwell time
* Running state
* Unattended state

### Event Reasoning

A deterministic Event Reasoning Engine converts object states into meaningful events.

Current event types:

```text
PERSON_ENTERED
PERSON_EXITED
ZONE_CHANGED
LOITERING
RUNNING
UNATTENDED_OBJECT
```

### Unattended Object Detection

Implemented and tested using:

```text
Object-person association
        ↓
Person moves away
        ↓
Object becomes separated
        ↓
Object remains stationary
        ↓
Separation exceeds threshold
        ↓
UNATTENDED_OBJECT
```

### Evidence Capture

Important events trigger keyframe capture.

Evidence is stored in:

```text
data/events/
```

### Persistent Event Memory

SQLite stores event information including:

* Event type
* Track ID
* Object class
* Timestamp
* Zone
* Confidence
* Description
* Evidence path

Database:

```text
data/sentinelai.db
```

---

## VLM

The current VLM is:

```text
microsoft/Florence-2-base-ft
```

Florence-2 is used as a **visual evidence verifier**, rather than the primary event-reasoning system.

Instead of asking the VLM to independently decide complex temporal events, SentinelAI provides focused questions such as:

```text
Is the person visibly holding the detected object?

Are the person and object visibly separated?

Is the object visible?

Is the person visibly interacting with the object?
```

---

## VLM Fine-Tuning

Florence-2 is being fine-tuned using **LoRA / PEFT** specifically for SentinelAI.

The training objective is to:

* Improve visual verification
* Reduce unsupported claims
* Handle ambiguous scenes
* Improve evidence-grounded responses
* Teach the model to return `UNKNOWN` when evidence is insufficient

Target response format:

```text
YES: ...
NO: ...
UNKNOWN: ...
```

The dataset includes:

* Positive examples
* Negative examples
* Hard negatives
* Ambiguous scenes
* Occluded scenes
* Insufficient-evidence examples

---

## Dataset

```text
dataset/
├── README.md
├── images/
├── train.jsonl
├── val.jsonl
└── test.jsonl
```

Each example contains:

```json
{
  "image": "scene_001.jpg",
  "detected_objects": ["person", "bottle"],
  "question": "Is the person visibly holding the bottle?",
  "answer": "YES: The person is visibly holding the bottle."
}
```

Training and test data are separated by scene or recording session to reduce leakage from near-duplicate video frames.

---

## Hallucination Reduction

SentinelAI explicitly distinguishes visible evidence from unsupported inference.

Examples:

```text
Person + object nearby
≠
Person is holding the object
```

```text
Person + backpack
≠
Person owns the backpack
```

```text
Object left behind
≠
Object is dangerous
```

When the image does not provide enough evidence:

```text
UNKNOWN
```

---

## Planned Components

### Retrieval + RAG

The system will retrieve relevant events and evidence from persistent memory.

```text
Event Database
      ↓
Retrieval
      ↓
Relevant Events + Evidence
      ↓
Local LLM
```

### Local LLM

The LLM will provide natural-language interaction over verified event history.

Example queries:

```text
What happened recently?

Was there an unattended object?

When did the person enter the zone?

What evidence was captured?
```

### Dashboard

Planned dashboard functionality:

* Live camera feed
* Detected objects
* Track IDs
* Current events
* Event history
* Evidence frames
* Alerts
* System status

### ESP32-CAM

The final sensing endpoint will use an ESP32-CAM.

```text
ESP32-CAM
    ↓
Camera Stream
    ↓
Laptop AI Pipeline
    ↓
Event Detection
    ↓
Visual Verification
    ↓
Alert / Response
    ↓
ESP32 Hardware Action
```

Possible hardware responses include:

* LED
* Buzzer
* GPIO actions

---

## Technology Stack

| Component        | Technology                |
| ---------------- | ------------------------- |
| Camera           | ESP32-CAM / Webcam        |
| Computer Vision  | OpenCV                    |
| Detection        | YOLO11n                   |
| Tracking         | ByteTrack                 |
| State Management | Python                    |
| Event Reasoning  | Custom Rule Engine        |
| VLM              | Florence-2                |
| Fine-Tuning      | LoRA / PEFT               |
| ML Framework     | PyTorch                   |
| Model Framework  | Hugging Face Transformers |
| Database         | SQLite                    |
| Retrieval        | Planned                   |
| Local LLM        | Planned                   |
| Dashboard        | Planned                   |
| Version Control  | Git + GitHub              |
| Development      | VS Code                   |

---

## Project Structure

```text
SentinelAI/
│
├── backend/
│   ├── api/
│   ├── camera/
│   ├── config/
│   ├── core/
│   ├── database/
│   │   ├── event_database.py
│   │   └── view_events.py
│   ├── detector/
│   │   └── detector.py
│   ├── event_engine/
│   │   ├── zone.py
│   │   └── event_engine.py
│   ├── evidence/
│   │   └── keyframe_capture.py
│   ├── llm/
│   ├── retrieval/
│   ├── schemas/
│   ├── services/
│   ├── state_manager/
│   │   └── state_manager.py
│   ├── tracker/
│   │   └── tracker.py
│   ├── utils/
│   ├── vlm/
│   │   ├── vlm.py
│   │   └── test_vlm.py
│   └── main.py
│
├── data/
│   └── events/
│
├── dataset/
│   ├── README.md
│   ├── images/
│   ├── train.jsonl
│   ├── val.jsonl
│   └── test.jsonl
│
├── models/
├── training/
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Development Roadmap

```text
Camera + Detection
        ↓
Tracking
        ↓
Temporal State Management
        ↓
Deterministic Event Reasoning
        ↓
Persistent Event Memory
        ↓
Evidence Capture
        ↓
Florence-2 VLM
        ↓
VLM Fine-Tuning
        ↓
Retrieval + RAG
        ↓
Local LLM
        ↓
Dashboard + API
        ↓
ESP32-CAM Integration
        ↓
Hardware Alerts
        ↓
End-to-End Evaluation
```

---

## Current Status

```text
Project Architecture       ✅
YOLO11n Detection          ✅
ByteTrack Tracking         ✅
State Management           ✅
Event Reasoning            ✅
Unattended Detection       ✅
Evidence Capture           ✅
SQLite Event Memory        ✅
Florence-2 Integration     ✅
VLM Fine-Tuning            🔄
Dataset Creation           🔄
Retrieval / RAG            🔲
Local LLM                  🔲
Dashboard / API            🔲
ESP32-CAM Integration      🔲
End-to-End Integration     🔄
```

---

## Goal

SentinelAI aims to combine:

**Lightweight sensing + real-time perception + persistent tracking + temporal reasoning + deterministic event detection + evidence-grounded multimodal AI + persistent memory + natural-language interaction**

into a single event-driven real-time intelligence system.
