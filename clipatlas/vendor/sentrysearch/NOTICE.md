# SentrySearch vendored core

Source: `ssrajadh/sentrysearch`

Locked upstream commit: `a89d1282fe52dd98aa71593cda86f8e8b4fbdd3b`

Upstream license: Apache-2.0.

Vendored in P0-2 without modifying these four upstream source files:

- `base_embedder.py`
- `chunker.py`
- `qwen_cloud_embedder.py`
- `dlq.py`

The byte-for-byte upstream Git blob identities are locked by `tests/vendor/test_sentrysearch_vendor.py`.

ClipAtlas runtime wiring and verified compatibility patches are intentionally deferred to P0-3. In particular, the upstream `qwen_cloud_embedder.py` at the locked commit still contains its original dimension/default configuration; P0-2 does not silently alter it.

## Apache License 2.0

Copyright notice and attribution remain with the upstream SentrySearch project and its contributors. The vendored files are redistributed under the Apache License, Version 2.0. A copy of the license is available from the Apache Software Foundation at `https://www.apache.org/licenses/LICENSE-2.0`.

The Apache-2.0 redistribution conditions apply to these vendored files. Any future ClipAtlas modifications to them must be clearly identified as modifications and must preserve applicable upstream notices and attribution.
