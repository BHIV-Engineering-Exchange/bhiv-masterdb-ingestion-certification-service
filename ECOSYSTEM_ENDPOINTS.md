# Ecosystem Endpoints — Status as of 6-7 Aug 2026

The task lead shared a full set of `PRAVAH_*` environment variables
naming base URLs for every adjacent service in the ecosystem. This is
the first time real, specific endpoint values existed for most of these
— everything before this was blocked on exactly this information. This
doc records what was actually checked and found, so the verification
work doesn't need repeating.

**Verification method**: `web_fetch` against each URL (this repo's own
sandbox has no outbound network access to any `*.onrender.com` or
`*.blackholeinfiverse.com` host — see the sandbox's network allowlist —
so live client code in this repo cannot reach these directly; only the
`web_fetch` tool, which has broader access, could check).

## Confirmed live, with a real discoverable contract

| Variable | URL | Finding |
|---|---|---|
| `PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE` | insightbridge-phase-4-2-integration-demo.onrender.com | **Live.** Self-describes as "InsightBridge API Gateway v4.2," names `/health`, `/ingest`, `/docs`, `/openapi.json`. A real client now exists: `services/insightbridge_client.py`, wired to `POST /observability/push-to-insightbridge`. |

## Responds, but ambiguously — needs a human to check

A 404 on the bare root path is genuinely ambiguous: MASTERDB's own
deployment does exactly this (no route at `/`), so a 404 here could mean
"real FastAPI/similar app, no root route" or "nothing deployed." This
sandbox's `web_fetch` can't distinguish the two without trying a
plausible sub-path, which its own URL-novelty restriction blocks unless
that path was independently surfaced (search or a prior fetch's links).
**Recommended**: check these directly (browser or `curl -i URL/docs` /
`URL/health`) — external, unrestricted access will resolve this in
seconds where this sandbox can't.

| Variable | URL |
|---|---|
| `PRAVAH_BHIV_BUCKET` | bhiv-bucket-i1l6.onrender.com |
| `PRAVAH_MASTERDB_API` | masterdb-ingestion-certification-service.onrender.com |
| `PRAVAH_BHIV_INSIGHT_CORE` | tantra-core.onrender.com |
| (unlabeled second InsightFlow candidate) | tantra-insightflow.onrender.com |
| `PRAVAH_BHIV_SARATHI` | sarathi-9n5g.onrender.com |

**The important one to resolve first**: `PRAVAH_MASTERDB_API` names a
*different* hostname than where MASTERDB is actually deployed
(`bhiv-masterdb-ingestion-certification.onrender.com`, from earlier in
this task's history). If other services call `PRAVAH_MASTERDB_API`
expecting to reach MASTERDB, they may be hitting the wrong place — or
that's the intended canonical URL and the actual deployment needs to
move/be aliased there. Needs a decision, not more investigation.

## Blocked from automated fetching (robots.txt) — likely real

| Variable | URL |
|---|---|
| `PRAVAH_PARIKSHAK_API` | parikshak.blackholeinfiverse.com/api |
| (MASTERDB's actual current deployment) | bhiv-masterdb-ingestion-certification.onrender.com |

Robots.txt blocking automated tools doesn't mean the service is down —
it's a common, deliberate anti-scraping setting. These are very likely
live; just not verifiable from an automated tool.

## Internal-only (private IPs) — not publicly reachable

`PRAVAH_BHIV_KARMA`, `PRAVAH_BHIV_CORE`, `PRAVAH_BHIV_CORE_EVENTS`,
`PRAVAH_BHIV_CORE_WEBHOOKS` — all point to `163.128.209.18:<port>`, a
private/internal IP. Not reachable from the public internet or this
sandbox. Whatever calls these needs to run inside that network, or
they need a public-facing proxy/tunnel.

## Unresolved placeholders — not real values

`PRAVAH_GURUKUL_API`, `PRAVAH_TRADE_BOT_API`, `PRAVAH_BLOCKCHAIN_API`,
`PRAVAH_SVACS_API`, `PRAVAH_BHIV_WORKFLOW`, `PRAVAH_BHIV_UAO`,
`PRAVAH_BHIV_KESHAV` all show `##YOTTA_URL:<name>##` — a secrets-manager
template string that hasn't been substituted with a real value in
whatever export produced this list. These aren't usable yet regardless
of network access.

## Other confirmed-format URLs, not yet individually checked

`PRAVAH_HR_API`, `PRAVAH_BHIV_HR_AGENT`, `PRAVAH_BHIV_HR_LANGGRAPH`,
`PRAVAH_CRM_API`, `PRAVAH_PROMPT_RUNNER_API`, `PRAVAH_TTG_API`,
`PRAVAH_UNIGURU_API`, `PRAVAH_WORKFLOW_BLACKHOLE_API`,
`PRAVAH_MITRA_API`, `PRAVAH_SAMRUDDHI_API`, `PRAVAH_SAMRUDDHI_HFT` — real
HTTPS URLs, well-formed, not checked individually in this pass (none map
directly to a service named in MASTERDB's current integration brief).
Worth checking if/when any of them becomes relevant.
