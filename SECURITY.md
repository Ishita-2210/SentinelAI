# Security and privacy

SentinelAI is a local monitoring prototype with no user authentication or role-based access. Use the presentation configuration at `127.0.0.1:8010`, one backend worker, and a trusted machine. Direct backend defaults bind to all interfaces; choose a localhost configuration for normal use. Do not expose the API, WebSocket or evidence directory publicly. Cross-origin access is not an authentication boundary.

Images, descriptions, timestamps and source identifiers may identify people or locations. Use authorized sources, obtain necessary consent, restrict local access and define a retention policy. No automatic evidence deletion occurs. Model inference stays local; initial model installation downloads upstream code/weights. Florence uses upstream custom model code, so inspect and trust that dependency before setup.

Keep `.env` files, credentials, machine-local `config.yaml`, Wi-Fi secrets, databases, evidence, recordings, firmware backups and model weights outside Git. Use committed example configuration and camera secret templates. Never force-add ignored data. `scripts/check_repository.py` scans tracked and unignored candidate files locally without uploading them; it is a heuristic check, not a guarantee. Review staged content manually.

If a credential was committed, do not paste it into an issue or logs. Record only the affected file/line, revoke or rotate it with its issuer, and coordinate any history remediation with the repository owner. This project does not automatically rewrite Git history.

Report a vulnerability privately to the repository owner using a private channel already agreed with them. If GitHub private vulnerability reporting is enabled, use **Security → Report a vulnerability** on the repository. Avoid public disclosure of exploit details or private footage until the owner has assessed the report. No dedicated security email or response-time guarantee has been established.

The language model has no command, filesystem or configuration tools. In recorded-facts mode, generated IDs are checked against retrieved event IDs and factual text comes from SQLite. Written explanations use supplied records or a Florence caption, are labelled as model interpretation and can contain inaccurate wording. Source links come from the host; unsupported generated references are rejected. Never use model observations as verified identity, intent or a sole basis for consequential decisions. Hardware constraints and unresolved electrical questions are documented in [hardware setup](docs/HARDWARE_SETUP.md).

Optional dashboard scene analysis saves the current annotated preview under the local evidence directory every 30 seconds while enabled. Turn off automatic descriptions for manual-only capture. Scene images remain private local data and are not automatically deleted; apply your own access and retention policy.
