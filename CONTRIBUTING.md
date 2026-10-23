# Contributing

Use the [README](README.md) installation and model setup. Keep changes focused and preserve local databases, evidence, models, firmware and recovery files. Do not include generated recordings, datasets, credentials or machine-local configuration in a pull request.

```powershell
git switch -c fix/describe-the-change
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
& .\.venv\Scripts\python.exe -m compileall -q backend scripts tests
git diff --check
& .\.venv\Scripts\python.exe scripts/check_repository.py
```

Add deterministic regression tests for correctness/security changes. Unit tests use synthetic images and mocked serial/model services; label that scope. Real inference and browser checks are separate opt-in operations. For UI changes, inspect desktop and narrow layouts, keyboard focus, unavailable models, stale frames, missing evidence and escaped untrusted text.

Firmware changes must compile for their documented reference target without uploading. Physical operations need a separately agreed procedure after the prerequisites in [hardware setup](docs/HARDWARE_SETUP.md). No guessed pin map is a verified target. Keep the primary telemetry firmware and recovery copy intact.

Before committing, review `git status`, the full diff and staged diff; run the local publication check. Source records and model outputs remain untrusted data. Preserve the separation of deterministic events, uncalibrated visual observations and validated source selection. Describe actual validation, failures and limitations in the pull request.

After staging, run `python scripts/check_repository.py --staged` with the project Python to scan the actual index, including existing tracked files.

No project redistribution license has been selected. Do not introduce a license or third-party media without the owner's decision and appropriate rights.
