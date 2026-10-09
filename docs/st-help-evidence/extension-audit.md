# ST extension help audit and metadata repair, 2026-09-24

The retained audit compares 23 pre-repair extension manifests in `scripts/lib/extensions` with read-only owner help extraction. For Typer owners, the capture calls the public `describe_app`; for `web` and `slopminer`, it calls each argparse parser's `format_help` (which has no usage-spec API). I also ran only `st <namespace> --help` for every namespace and selected nested `--help` paths. The [machine-readable baseline audit](extension-audit.json) lists the retained namespaces, path counts, missing paths, option-name differences, Typer usage differences, owner revisions and dirty tracked paths, and their [raw owner/runtime captures](extensions/). Before repair, these manifests and their owners each exposed **272 help paths**. All 23 installed root help outputs matched their manifests. All 23 manifest effect sets matched the enabled registry grants; this checks metadata consistency, not every command's runtime side effects. No command callback, service, model, or mutation was invoked.

The retained repairs cover `automations.json`, `learn.json`, `jobs.json`, and `slopminer.json`. The first two use owner `describe_app` help and usage verbatim; Jobs usage matches owner `describe_app`; Slopminer root `inspect` text matches its parser. Before editing, I verified the registered owner executables expose all 17 Automations help paths and both Learn `--full` flags ([resolved executable captures](extensions/)). After editing, [nine retained `st ... --help` paths](extension-post-fix-validation.json) matched checkout metadata. IDs, wrapper metadata, effects, and registry grants were preserved. The full Automations owner help costs more bytes than its former manual summary (root 248→1,049; all paths 1,264→4,583), but exposes the real command descriptions, flags, defaults, and ranges. Parent-owned `search.json` and `models.json` were untouched. Packaging/deployment remains with the parent.
At this checkpoint, a full static comparison found no missing help path or owner option name in any of the 23 retained checkout manifests. Remaining text differences are the intentional Browser wrapper, `st` executable-name/wrapping differences in Design, Graph, Web, and Slopminer, plus parent-owned Search wording. This does not validate every owner usage sentence or per-operation effect by execution.

| Namespace | Pre-repair / owner paths | Baseline finding |
| --- | ---: | --- |
| agents | 8 / 8 | Exact help and usage |
| automations | 17 / 17 | Hand-condensed help; missing `runs --offset`, defaults/ranges and command descriptions; usage drift |
| browser | 1 / 1 | Hand-authored source usage matches installed; intentionally differs from generated Typer help |
| complete | 1 / 1 | Exact |
| design | 11 / 11 | `st design` versus `design` command qualification only; no flag drift |
| feedback | 11 / 11 | Exact |
| graph | 11 / 11 | `st graph` versus owner executable `code-graph` prefix only |
| jobs | 44 / 44 | Help exact; one owner usage entry dropped `task_types` |
| learn | 46 / 46 | Two stale `--full` help paths and one stale usage entry |
| mandates | 1 / 1 | Exact |
| memory | 18 / 18 | Exact |
| models | 2 / 2 | Exact |
| note | 1 / 1 | Exact |
| persona | 10 / 10 | Exact |
| portfolio | 23 / 23 | Exact |
| prompt | 15 / 15 | Exact |
| search | 1 / 1 | Installed help predates owner's pending source update |
| selection | 4 / 4 | Exact |
| skills | 8 / 8 | Exact |
| slopminer | 12 / 12 | Executable prefix and one `inspect` summary differ; no flag drift |
| ui | 16 / 16 | Exact |
| web | 5 / 5 | Argparse executable-name/wrapping difference only; no flag drift |
| wiki | 6 / 6 | Exact |

[Learn](extensions/learn.json) omitted `--full` from both `status` and `pwn status`; its stale `status` usage said “full learning state,” while owner usage says the default is compact and `--full` requests complete state. [Automations](extensions/automations.json) had 17 handwritten short help entries rather than the owner-described option tables. `runs` omitted the real `--offset` pagination option. The `runs`/`list` entries omitted owner defaults (`--limit` 50/100, `--offset` 0) and allowed ranges; the root compressed the command list into one sentence and dropped owner command descriptions. Several usage entries lagged source syntax, including `runs --limit` and `review --through-run-id`.

The [search capture](extensions/search.json) shows a pending dirty `code_intelligence/cli/search.py` in the owner checkout: source help explains auto source verification, local recovery, and when to use `--scope checkout`; pre-repair installed help used older scope wording. Parent owns its package and metadata update. [Browser](extensions/browser.json) intentionally uses its owner-maintained `_USAGE` text instead of Typer's generated wrapper. Its 2,962-byte root repeats the `check` route in usage, examples, and local-profile guidance; shortening it without losing the isolation rule would require a deliberate owner change. `design`, `graph`, `web`, and `slopminer` mostly differ because public owner executable names differ from the `st` dispatcher name; these are not option/default regressions. Slopminer's root `inspect` summary used “scoped guidance” where owner source says “all pending profile guidance”; both explicitly said “without evaluation.”

The audit was captured against SummitFlow checkout `e31cb77933783e9d4e4804186668350d970fe5bc`; the manifest and registry paths were clean. Each raw capture records its owner's own Git revision and tracked dirty paths. The review artifacts are under ignored `.dev-tools/st-help-review`, so they need explicit inclusion if committed. Core ST help is outside this audit and is being reviewed separately.

Focused verification after the core routing fix: `st check pytest -- backend/tests/cli/test_extensions.py` passed **20 tests**. The earlier in-flight run failed one prefix-option routing assertion while that separate core fix was unfinished; its raw details remain `.dev-tools/pytest-18d8564c52a1ed76-2560087-d179fae5-details.txt`. The passing run is `.dev-tools/pytest-18d8568ad8269f80-2573053-84f8030b-details.txt`.

The final `st --help` review found ten Agent Hub extension summaries that named ownership without explaining the command. Their metadata summaries now state the source-backed purpose and read/write action in one line; [all ten render without truncation](extension-summary-validation.json). The two owner-source help defects were then corrected in Agent Hub: `mandates.py` puts global `--no-compact`/`--human` before the command in readable examples, and `automations.py` gives the first seven commands concise descriptions grounded in their existing `@usage` purpose and API behavior. Only those two help maps were regenerated from [owner source `describe_app`](extensions/agent-hub-source-after-docstrings.json), preserving manifest summaries and wrappers. [Nine local `st --help` paths](extension-owner-help-final-validation.json) exactly match that source. The registered Agent Hub wheel still needs the parent's package/lock sync before its direct executable help reflects these source docstrings.
