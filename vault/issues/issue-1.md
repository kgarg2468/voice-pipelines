---
type: issue
number: 1
title: "Engine rejects local connections without an API key"
state: closed
url: https://github.com/kgarg2468/company-brain-demo/issues/1
---

Reported by **Charlie** (engineer). The OSS engine returns `No authorization provided` when a client connects to a local engine without a key. We need real per-task auth instead of a single shared global key.

[[people/charlie]] [[features/auth-refactor]]
