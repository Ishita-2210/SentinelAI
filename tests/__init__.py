"""
SentinelAI — Focused deterministic test suite.

Runs without a camera, model download, or GPU.
Tests: schemas, state manager, event engine, database, VLM normalizer,
       evidence path construction, API startup, config defaults.

Run with:
    .\.venv\Scripts\python.exe -m pytest tests/ -v
"""
