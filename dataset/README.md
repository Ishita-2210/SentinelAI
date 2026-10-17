# SentinelAI VLM dataset

Training data for fine-tuning Florence-2 as a visual evidence verifier
(`python -m training.train_lora`).

```
dataset/
├── images/          keyframes (jpg/png)
├── train.jsonl
├── val.jsonl
└── test.jsonl
```

One JSON object per line:

```json
{
  "image": "scene_001.jpg",
  "scene": "session_A",
  "detected_objects": ["person", "bottle"],
  "question": "Is the person visibly holding the bottle?",
  "answer": "YES: The person is visibly holding the bottle."
}
```

## Answer format

| Prefix | Use when |
|---|---|
| `YES:` | the image clearly shows it |
| `NO:` | the image clearly shows the opposite |
| `UNKNOWN:` | occluded, blurry, out of frame, or otherwise not enough evidence |

Always give a short reason that describes only what is visible.

## Rules that keep the model honest

- Include hard negatives (person near an object but not holding it) and
  plenty of `UNKNOWN` cases. A model trained mostly on `YES` will say `YES`.
- Set `scene` to the recording session. All frames of one session must be in
  the same split, otherwise near-duplicate video frames leak from train into
  test and inflate the accuracy.
- Questions should match the ones the pipeline asks
  (see `EVENT_QUESTIONS` in `backend/vlm/vlm.py`).

Check the dataset before training:

```
python -m training.validate_dataset dataset
```
