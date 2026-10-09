# ST help review for agent use

The installed ST help surface was reviewed against command registration, owner
source, active owner executables, and generated extension metadata. The review
retains 538 actual help invocations: 242 native outputs including hidden aliases,
272 extension pages across 23 namespaces, and 24 safe manual help forms.
Another 46 manually dispatched forms were inventoried structurally. Every captured
page returned successfully with nonempty output. No native command, flag, default,
type, requiredness, hidden alias, extension binding, or existing help path was lost.

## Corrections

- Root task registration now preserves descriptions supplied by owners. Root help
  identifies ST as tools for agents, explains global-option placement and output
  precedence, and gives concrete purposes for previously generic extension entries.
- Native help now describes actual dry-run support, project selection, rebuild
  scope, dependency-review revisions, session limits, acceptance options, and task
  creation inputs. Nested database help gives the requested command's syntax.
- `autocode --at` previously reported scheduling while dispatching immediately.
  It now rejects the unsupported option before calling the client; immediate
  dispatch remains available without `--at`.
- Generated help exposes Learn's `--full` and
  Automations pagination, defaults, required inputs, and command purposes.
- Search help matches the delivered capability guidance: start with default
  search, consume returned source, narrow with existing flags, and select checkout
  scope for an alternate or offline checkout.
- Help routing now uses optional owner-generated option arities. For example,
  `st models --id list --help` correctly describes the root command rather than
  mistaking the ID for a subcommand. Static help still requires no owner execution.
- Invalid output-flag examples were corrected in Mandates, desktop UI/selection,
  and health help. Owner help remains in the owner package; SummitFlow retains
  shared dispatch, metadata, packaging, and integration.

## Output cost and limits

Counts below estimate tokens consistently as `ceil(UTF-8 bytes / 4)` per call.
They measure emitted help, not model tokenizer counts or successful task duration.

| Requested page | Before | After | Reason |
| --- | ---: | ---: | --- |
| `st db query --help` | 191 | 38 | Exact query syntax replaces an unrelated full command list. |
| `st --help` | 1,466 | 1,560 | Restored task descriptions and useful command purposes. |
| `st search --help` | 425 | 551 | Current-source behavior and narrow continuation guidance. |
| `st automations runs --help` | 19 | 75 | Restored pagination, defaults, ranges, and purpose. |

The artificial sum of retained captured pages grew from 58,596 to 59,612 estimated
tokens, with nine additional captures. This is not a universal token-saving claim.
The demonstrated benefits are correct navigation, complete syntax, and shorter
targeted database help. Larger pages were retained where the previous version
omitted information needed to act correctly.

This is exhaustive route inventory and static contract review, not execution of
every mutating operation or proof of every remote backend response. Malformed
extension arguments conservatively return the nearest known help page; ST does
not reproduce every owner's argument-parser error. Legacy backup job-ID lookup
remains unsupported and is explicitly labeled. No desktop actions were performed.

## Evidence and verification

- [Native audit](st-help-evidence/native-audit.md) and
  [extension audit](st-help-evidence/extension-audit.md) retain findings,
  source references, owner revisions, raw help, and dispositions.
- [Independent verification](st-help-evidence/verification/report.md),
  [comparison](st-help-evidence/verification/comparison.json), and
  [raw installed inventory](st-help-evidence/verification/after.json)
  establish route/signature compatibility and output costs.
- Focused regressions cover registration metadata, static help safety, option
  values that equal command names, targeted DB help, and rejection of unsupported
  scheduling before client calls. Canonical gates passed, including 3,545
  SummitFlow backend tests and 229 frontend tests before final packaging checks.
- Package identity and managed runtime evidence are retained beside the audit as
  `installed-packages.json`, `deployed-packages.json`, `runtime-parity.json`, and
  `verification/runtime-review.md`. The task completion record links the exact
  managed deployment receipt and final validation artifacts. Publication is
  separate from these local checkpoints.
