# Codebase cleanup plan (agent-hub, summitflow, aico, nightshift, neri)

The single plan for this cleanup. Every decision from the owner conversation is recorded here, and no separate task is filed.
Started 2026-11-02. The evidence is the per-project audits in `audit/`. Where the coordinator re-checked an audit claim live, the result is noted.
Neri rule: line counts are fine. Never review case or hunter details.

Status: **Decided** = the owner said do it. **Proposed** = recommended and checked, awaiting a go-ahead. **Owner call** = needs your judgment. **Exploring** = still being designed.

## Decisions log
- 2026-11-02 **Cut `st claude` and the Agent Hub Claude worker.** Agents ran `st claude task` once in 120 days: on 2026-10-09, to test it after the restore. Every other mention was a `--help` read or text inside another command. Native subagents and Aico sessions do this work now.
- 2026-11-02 **Notes stay, rebuilt properly in Aico.** "Just because I haven't used it doesn't mean I don't need it." Google Keep is your current notes app. See the notes section below. The SummitFlow and agent-hub notes code goes away once Aico notes exist and the 36 existing notes are moved over.
- 2026-11-02 **Notes must work with gem down, and stay on our hosts.** "Rather not rely on Cloudflare... fine for access, not ideal for storage." So the notes service runs on both hosts and they sync (see "Notes store" below). Cloudflare stays limited to Access and tunnels.
- 2026-11-02 **Wife's shared grocery list: deferred.** "We can add that later if I want." If it comes back: her Google account through Cloudflare Access on an existing hostname, with no new subdomain.
- 2026-11-02 **Photo text may call Gemini directly.** If the bake-off shows Gemini is best, extraction runs the `agy` subscription CLI on whichever host is up, and Agent Hub becomes an optional route for this one module.
- 2026-11-02 **VMs:** agents may start any VM they need (e.g. VM 180 to check the portfolio-ai and jobinator leftovers) and stop it again when done. Only VMs they started get stopped.
- 2026-11-02 **Kept as is:** the Nightshift native tray and inbox panel (you moved off the website on 10-30, so T4 is withdrawn), the ledger and the drill, the aico lifecycle harness and real-session smoke scripts, and the Neri warp and oracle exits.
- 2026-11-02 **Wake-on-LAN changes need your OK first.** That covers the Wake button, the wake commands in hosts.json and any router or BIOS changes. Run each by you before building it. Testing the existing WoL (shut down, wake, time it) is fine without asking.
- 2026-11-02 **Router cloudflared: no.** There isn't enough flash for it, firmware upgrades wipe it, and gem already runs its own connector (tunnel `9483e71c`, serving `pve.summitflow.dev`).
- 2026-11-02 **gem's Aico container may SSH into the Proxmox host**, only for a phone rescue shell and alerts while the workstation is off. That means one restricted key and the container's address in the `management` ipset, done when CT 190 is built.
- 2026-11-02 **Nightly notes export uses its own Drive token**, limited to its `SummitFlow-Notes` folder (`drive.file`). You sign in once when the export is built; the backup's token never goes to gem.
- 2026-11-02 **Wake workstation button: not now.** You said "hold off on this for now and revisit it at a later date if i want". Nothing gets built; `wake-ws` on gem stays the manual route.
- 2026-11-02 **Phone Photos multi-select works** (you tested it on your phone).

## Cross-project
| # | Item | Status | Size / gain |
|---|---|---|---|
| X1 | Bring the full test check back under its time target: nightshift 154s vs 60s (was 32s), summitflow 121s vs 90s, aico 100s vs 60s, agent-hub 125s vs 116s | Proposed | Check time |
| X2 | Stop tests that assert exact wording or copy, in all five repos (nightshift alone has 314) | Proposed | 3-6k test lines |
| X3 | Run the Rust and Kotlin tests in a check: summitflow host-monitor (54 tests), nightshift desktop and android (61) | Proposed | Closes a gap |
| X4 | Remove notes and notes-ui from summitflow and agent-hub after Aico notes ship | Decided (after N1-N3) | About 6k lines |

## Notes in Aico (Exploring)
Facts:
- **SummitFlow:** 36 notes (19 "prompt", 17 "note"). None created since 2026-07-14. Two were edited on 2026-10-23, both scoped to aico.
- **agent-hub:** its notes page shows agent-hub-scoped notes, and there are 0.
- **Earlier decision:** the 2026-10-10 Tether plan removed notes and prompts from A-Term, which is now Aico (`aico/docs/history/migration-plan.md:60`). Bringing notes back as an Aico feature now reverses that decision on purpose.
- **Aico:** you use it daily as a phone PWA, and it has its own database (`web/server/src/db.ts`). That makes it the natural home for quick capture.
- **Google Keep:** the official API is for Google Workspace (enterprise) accounts only. Consumer Gmail accounts can't use it. Live sync would need gkeepapi, which is unofficial, reverse-engineered and needs a Google master token. Google Takeout can export Keep as JSON for a one-time import.

Owner requirements (2026-11-02, discussion phase, no changes yet):
- A full, proper notes feature designed into Aico, with notes backed up to Google Drive.
- What goes in Keep today: personal notes, recipes, grocery lists, and car service reminders. Recipes and car service records exist only in Keep, so the Takeout import must bring them over complete, photos included, before Keep is retired.
- Photos of handwritten notes (e.g. grocery lists) must turn into accurate text.
- Receipts and similar documents get scanned too.
- Design with portfolio-ai in mind: one canonical owner per kind of data, centralized where that fits.

portfolio-ai today (read-only look):
- **Size:** 150k backend lines, 51k of them household.
- **Phone app:** it is a PWA.
- **Captures:** `api/captures.py` and `household_capture_service.py` handle `receipt` and `shelf_tag` captures that go through a review step.
- **Text extraction:** RapidOCR for printed text plus an Agent Hub vision call (`_household_document_llm.py`).
- **Receipt handling:** Costco and Walmart receipt parsers, receipt reconciliation, unit-price and price checks, and a ShoppingPilot that compares in-store unit prices for repeat purchases.
- **Household:** household members with scoped access.
- **Backups:** uploads are encrypted and backed up together with its database.

Owner answers (2026-11-02):
1. **Sharing:** only you use it today. A link your wife can open to add items to a grocery list would be nice.
2. **Outages:** you want to keep reading and taking notes when davion-sidarli or davion-gem is offline, possibly from Google Drive.
3. **Vehicles:** your cars in the system with service history and recommended maintenance, tracked by both date and mileage. Capture works like this: you photograph the odometer and say "just changed the oil, rotated the tires". You had planned to build this anyway, so it may be built as part of this work. Past records can be requested from the Subaru dealership and Pep Boys.
4. **Capture:** you asked for a recommendation, with room for more kinds of capture than notes and receipts.

Facts that shape the design:
- **No login of its own:** Aico gives a shell on the host and relies on Cloudflare Access (`aico/docs/remote-access.md`). A guest link must never go through `aico-web`.
- **No offline mode:** Aico's service worker passes every request straight through (`web/frontend/public/sw.js`). When the host is down, the phone app is down.
- **Docs checklists (unverified):** the Google Docs API probably doesn't expose whether a checklist item is ticked. That's why Google Docs shouldn't be the store for lists.

Recommended design (discussion; nothing built):
- **Notes store:** Aico's database on the host is the source of truth. On top of that:
  - The phone keeps a full offline copy. Notes and captures made offline queue up and sync when the host is back.
  - Every note is mirrored to a Google Drive folder as a readable copy, with its photos.
  - A Drive "Inbox" folder takes whatever you drop in during an outage, and it is imported later.
  - The existing nightly Drive backup also covers the database.
- **Rejected:** Google Drive as the database. Google's formats become the schema, checklist state may not be readable, and vehicles and receipts still need the host.
- **Shared lists:** deferred (see the decisions log). Notes are built for one user, in a way that doesn't block adding sharing later.
- **One capture button in Aico, with a router:**
  - A photo, voice note, text or file goes to the Agent Hub vision model, which suggests a type and where it belongs.
  - A grocery item files itself. Money and vehicle records wait for your one-tap confirmation.
  - Each type has exactly one owner, and the type-to-owner mapping is data, so adding a new kind of capture doesn't mean building a new app.
  - The original is stored once, by its owner. Receipts stay encrypted in portfolio-ai.
  - portfolio-ai's capture page stays as its review screen.
- **Vehicles:** portfolio-ai owns them, widening its scope from money to the household:
  - Each car's odometer readings and service history, linked to receipts and their costs.
  - Maintenance schedules per model and year, stored as data.
  - Due-soon alerts by Nightshift push.
  - Import of dealer and Pep Boys records, plus the car notes in Keep.

Proposed ownership (to discuss):
- **Aico:** owns notes (text, checklists, recipes, reminders) and the phone capture button.
- **portfolio-ai:** stays the owner of receipts and anything about money and prices. Aico hands receipt photos to its capture API and never keeps a second copy.
- **Vision:** handwriting needs a vision model, because RapidOCR only reads printed text. Each app keeps its own parsing.
  - One small `vision-extract` module takes a typed JSON schema and returns results. It runs on whichever host is up.
  - If the bake-off picks Gemini, it calls `agy -p --output-format json --json-schema` (the subscription, OAuth), with Agent Hub as an optional route.
  - Today, receipts use `household-receipt-vision` (`portfolio-ai .../household_review_agent_service.py:55-74`). Its primary is `local/qwen3-vl:8b` on the workstation GPU, and its fallback is the free-tier `gemini-3.1-flash-lite`. So receipts already depend on the workstation, and Google's free tier may use the data.
  - **Bake-off first.** Five samples: a handwritten grocery list, a receipt, an odometer, a service invoice and a recipe photo. Compare agy, `gemini-3.8-flash` (API) and `qwen3-vl:8b`, scored by exact transcription. agy accepts images (checked 2026-11-02 on a made-up grocery-list image): the prompt gives the file path, and agy reads it with its file tool. `--json-schema` returns the structured result.
    - `gemini-3.8-flash-low`: exact transcription in 23 s, about 34k tokens.
    - The default model, with no `--model`: also exact, but 175 s and about 230k tokens.
    - So `vision-extract` pins a Flash model, and captures are processed in the background.
    - **Results (2026-11-02, your 3 photos: a Costco receipt, a dashboard odometer, a handwritten grocery list; you said 3 is enough).** Same prompt and JSON schema for every model, photos scaled to 2048 px. Ground truth read by hand from the full-size photos.

      | Model | Receipt (24 rows, totals, date) | Odometer (33396, trip 44.6) | Grocery list (21 lines) | Time per photo |
      |---|---|---|---|---|
      | **agy `gemini-3.8-flash-low`** (subscription) | **24/24** rows; subtotal, tax, total, date, store all right | **Right**, fields filled | **21/21** read as written; 2 wrong strike-through marks (avocado, bread crumbs, which is underlined) | 16-26 s |
      | `qwen3-vl:8b-instruct` (local GPU) | 23/24 (`48Z` read as `4BZ`); totals right; no date or store | **Wrong** (33395), fields empty | 18/21 (butler, milk 2+/, rice Cans); missed the strike-through | 4-59 s |
      | `gemma4:12b-it-qat` (local GPU) | Empty output | Read 33396 but left the fields empty | Dropped one line and **made up two items** | 15-78 s |

      - **Winner: agy Flash.** `vision-extract` calls it directly. Local qwen3-vl stays as the fallback, and anything it reads is flagged for a look.
      - Skipped the `gemini-3.8-flash` API run. It's the same model family as the subscription, and the free-tier API may use personal photos.
      - For Milestone 2: keep the writer's text (`see weeds`, `pamagrants`) and add a cleaned-up item (`seaweed`, `pomegranates`) for search and checklists. Strike-through is a hint you can fix; the photo stays attached.
- **Nightshift Web Push:** delivers reminders, since it is the only owner-alert channel.
- **Backups:** the Aico notes database and photos join the existing registered Google Drive backup. No separate Drive sync.

Proposed shape:
- **N1.** Aico owns notes in its own database: quick capture on the phone, checklists, pin, labels and search.
- **N2.** Agents can read notes and act on them through `tether` (e.g. "send this note to a session"). This is the thing Keep can't do.
- **N3.** One-time import of the 36 SummitFlow notes and a Google Keep Takeout export. No live Keep sync.

### Notes store: works with either host down (decided 2026-11-02)
- **Same notes service on both hosts,** each with its own SQLite file, next to the Aico front door on that host. Whichever host is up serves your notes.
- **Both hosts accept edits; there is no leader and no failover.**
  - Every list item, note field and attachment is its own row, with a row id, `updated_at`, the host that wrote it, and a delete marker.
  - When both hosts are up, a small sync swaps changed rows every minute over the LAN, and right after each write.
  - The newer edit wins for each row. Adds never collide, because list items are separate rows. Two edits of the same text while the hosts were split keep the newer one and save the older as a revision.
- **Photos are files named by their hash.** Each host copies missing ones from the other.
- **Readable Drive copy:** a nightly Markdown and photo export to Drive from whichever host is up, reusing the existing Drive backup route.
- **Both hosts down:** the PWA opens the last-synced notes read-only from its cache. That's a small addition to the passthrough `sw.js`. Optional, but cheap.
- No CRDT library, no database replication, no Cloudflare storage. Expected size: a few hundred lines plus tests.
- **Test:** split the hosts, edit the same list on both, then rejoin them. Both adds survive, the newer text wins with a saved revision, and deletes stay deleted. Live check: add an item from phone Aico with gem off, power gem on, and the item appears there.

### Standard agent interface for Aico (Decided 2026-11-02: one adapter per tool, keep the real TUIs)
You asked whether a standard exists, so Aico isn't held together with per-tool hooks. You said yes to a Claude-over-ACP spike, then "figure out what's best". Reading T3 Code's source (pingdotgg/t3code @6f41364, scratch clone `/srv/scratch/t3code-ref/t3code`) answered the question without one.
- **ACP and the vendor SDKs can't attach to a TUI you're looking at.** They launch the tool headless, and the app draws the chat itself. That's what T3 Code is.
- **That costs a lot of code.** T3 Code's Claude adapter is 11.7k lines, Codex is 8k plus 60k of generated app-server protocol, and its ACP packages are about 38k.
- **T3 Code doesn't use ACP for Claude or Codex either.** It uses the Claude Agent SDK and `codex app-server`. ACP is its route for tools without a native interface (Antigravity, Grok, Cursor and others), behind one `ProviderAdapter` contract (start, steer, interrupt, resume, events).
- **Our mess is where the per-tool code lives.** Per-tool knowledge is spread over about 8 Tether files (`agent-state.ts` alone has 27 per-tool branches, plus `tools.ts`, `model-switch.ts`, `lifecycle/tui/context.ts`, `root-control.ts`, `continuity.ts`), SummitFlow `scripts/lib/coord_inbox.py` (547 lines) and `tether/integrations/pi/aico-due.ts`. Each tool's own extension points (Claude and Codex hooks, the Pi extension) are the supported way to work with a live TUI; they're just not organized.
- **Decision:** keep the real TUIs, and borrow T3 Code's shape instead of its protocol. Each tool gets one adapter module under `tether/src/lifecycle/tui/` (the registry already exists), all implementing one contract: launch, busy or idle, deliver now, deliver at the next turn, install context and hooks, resume, model switch. One conformance suite runs every adapter through the same checks: unit tests, plus a short live smoke per tool. Adding a tool means one file plus passing the suite. Headless runs (Agent Hub) keep using `stream-json` and `codex app-server`.
- **Not doing:** an ACP or SDK chat UI in Aico. Revisit only if you want a phone-first chat for headless sessions.
- **Status:** starts after the delivery fix for all tools (running now) lands, since it touches the same code. Medium-large.

### Debt guards in `st check` (On hold 2026-11-02: wait for the consolidation)
**Your call:** not yet. You may fold summitflow, agent-hub and nightshift into aico, after pruning them hard. Guards and baselines built for those three repos now would be thrown away.
- **Plan:** when the pruning starts, run the dead-code and duplication tools once, as reports for finding what to cut (no gate).
- **After the consolidation,** add only the two cheap, fast guards to the one repo: dead code, and new suppressions, skipped tests or removed asserts in a diff.
- **Skipped as ceremony:** mutation testing, complexity and size ratchets, logging reviewer-finding outcomes, and the cleanup job.

### Possible consolidation into aico (Owner idea 2026-11-02, not started)
You're considering folding summitflow, agent-hub and nightshift into aico, with heavy pruning first. Nothing is being done on it yet. Keep it in mind when sizing work in those three repos: prefer cuts over new structure there. The per-tool adapter rework lives in aico/tether, so it holds either way.

#### Original proposal (for reference)
The idea: automated checks that stop agents adding tech debt, so the cleanup doesn't creep back.
- **Already have:**
  - the quick check on every `st commit`, and the full and deep lanes
  - `st check budget`, which ratchets LOC, test ratio and gate time (it's currently over: the gate takes 96 s against a 90 s target)
  - import-linter in agent-hub only
  - radon in summitflow
  - the read-only `code-reviewer` agent
  - the hooks that block stash and reset
  - the search-first rule in CLAUDE.md
- **Missing:**
  - a diff check for new suppressions, skipped tests and removed asserts
  - duplication (jscpd)
  - dead code (vulture, knip)
  - per-file size and complexity ratchets that fail only on new or worse violations
  - module-boundary rules outside agent-hub
  - mutation testing on changed code
  - a record of which reviewer findings led to a fix
  - a bounded cleanup job
- **How it fits:** build once as shared `st check` stages with per-repo baselines, not a separate setup per repo. Fast checks go in quick; slow ones (mutation, duplication, dead code) go in the deep or nightly lane, so commits don't slow down.
  - Baselines only tighten automatically. Loosening one takes an explicit flag with a reason, which shows in the nightly report; there's no approval tap.
  - Ship in SummitFlow first, then roll out to agent-hub, aico, nightshift and neri. Neri's checks run on code only.
  - Its first runs also produce dead-code and duplication lists, which feed the cleanup milestones here.
- **Differences from the prompt:** commits go to main through `st commit`, not a branch. The reviewer is the existing `code-reviewer` agent. The cleanup job reuses the scheduled-agent tooling, off by default.
- **Size:** medium for SummitFlow, then small per repo.

## Hosts: always-on (davion-gem) vs on-demand (davion-sidarli) (Exploring)
Owner decisions (2026-11-02):
- Notes must keep working with either host down (updated 2026-11-02; see "Notes store"). The offline phone queue and the Drive Inbox stay dropped, and the Drive backup stays.
- You switch servers and services on and off yourself. Build no automatic power management and no auto-start.
- davion-sidarli costs more to run, so whatever must be available all the time belongs on davion-gem.
- portfolio-ai and jobinator-4000 already moved to gem, in VM 180 `apps`. It is off by your choice.

Measured 2026-11-02:
| | davion-sidarli | davion-gem |
|---|---|---|
| Hardware | Ryzen 7 7800X3D, RTX 4080 SUPER, 30GB RAM | Ryzen 7 6800H, 30GB RAM, PVE 9.2 |
| CPU package power, as idle as it gets | 41W plus about 7W GPU, in a full desktop | 17W, including the guests that are running |
| Load | Agent work | Load 1.0. 25GB RAM free, 54G free on root, 310G free on the thin pool |
| What runs | tether, aico-web, agent-hub (backend, frontend, 2 workers), summitflow (backend, frontend, worker), shared Postgres (2.9GB RAM; agent_hub DB 5.3GB, hatchet 2.0GB), Hatchet, Redis, searxng, ollama, nightshift desktop pieces, neri backend, cloudflared, caddy | VM 100 st-browser (8GB), LXC ominull-hub, restic-append, opencanary |

Other facts:
- **Agent sessions on gem:** Tether already links other hosts over SSH (`tether-link@<host>`, `aico/docs/INSTALL.md`). A linked host's link "retries quietly while the host is down and never powers it on", which matches how you run things.
- **Firewall:** gem's firewall only lets the workstation in to manage it. Gem services would reach the phone through a cloudflared connector on gem, which makes outbound connections only.
- **Wake-on-LAN:** enabled on the workstation (enp8s0, `Wake-on: g`). Optional. You power things on yourself.

Proposed split:
- **Always-on, on gem:**
  - VM 180 with portfolio-ai (receipts, and vehicles next) and jobinator.
  - Aico's front door: aico-web plus a gem Tether that holds notes (synced with the workstation's copy) and capture, and links to the workstation's Tether when it is up. When the workstation is off, its terminals show as offline.
  - Security and backups: ominull-hub, opencanary, restic-append, and Nightshift's off-host watchdog and push.
  - The cloudflared connector for those hostnames.
- **On-demand, on sidarli:** agent sessions (Tether), agent-hub, summitflow and its Postgres, Hatchet, Redis and searxng, ollama and the GPU, browser automation, host-monitor, Nightshift's workstation pieces, and the neri backend.
- **On-demand, on gem:** VM 100 st-browser (8GB, only agents use it), VM 200 agent-work, the labs, the neri VMs, and VM 130 st-ci-runner.

Gaps to settle before anything moves:
- **AI calls with the workstation off:** settled by the direct `vision-extract` route on gem, if the bake-off picks Gemini. Otherwise captures save the photo right away and fill in the text when the workstation is back.
- **Backups of gem data:** the Google Drive backup job runs from sidarli. Always-on data on gem needs a backup that runs from gem. Confirm coverage before any durable data moves.
- **Aico on gem:** aico-web's file browsing and uploads now assume the workstation's disk. Check what still works while the workstation is off.

### Light dev and hunting with only gem up (owner question 2026-11-02)
Today the answer is **no**:
- **The VMs depend on the workstation.** agent-work (VM 200) and neri-hunters (VM 201) run on gem, and their Claude Code and Codex logins are already there. But both reach SummitFlow (8001), Agent Hub (8003) and the Neri backend (3017) through the workstation's `tether-link` forwards. Their health checks require those (`~/.config/tether/hosts.json`). With the workstation off, there is no `st`, no tasks, no checks, no memory or context, and no `st neri`.
- **There is no way in.** Aico runs on the workstation. Both VMs sit on labnet, and only the workstation can connect in.

To make the answer yes, also put the **platform core** on gem: SummitFlow, Agent Hub, the Neri backend and their Postgres, Hatchet and Redis. Measured on the workstation, that is about 5GB of RAM; the DBs are agent_hub 5.3GB and hatchet 2.0GB. Gem's Tether then links to VMs 200 and 201, so Aico on gem reaches their sessions.
- **The workstation becomes the heavy machine,** turned on when needed: GPU, desktop, big test runs, and the main checkouts under `/srv/workspaces`.
- **Work done in VMs while the workstation is off** stays in the VM's git until the workstation is back. Agent shells can't push.
- **Gem RAM (30GB) only fits one dev VM at a time:**
  - Fixed: platform about 5GB, plus apps 6GB, plus the always-on LXCs.
  - Then one of: agent-work 16GB (balloon 8), neri-hunters 12GB (balloon 6), or st-browser 8GB.
- **This also fixes the gap about AI calls with the workstation off,** because Agent Hub would be on gem.
- **Cost:** a large migration. You would move the shared Postgres, point workstation services at gem, and check every path that assumes `127.0.0.1` on the workstation.

### What still works with one host down (owner question 2026-11-02)
| | Today | After phase 1 (household apps and Aico front door on gem) | After phase 2 (platform core on gem) |
|---|---|---|---|
| **gem off, sidarli on** | Full dev on sidarli: Aico, agents, `st`, checks, agent-hub, summitflow, `st neri` state. Hunting still works: each hunt runs in a container on a host from `hunts.hosts`. The neri-hunters VM is tried first, and `local` is next. A VM whose Proxmox node is offline is skipped (`neri/docs/st-neri.md:263-277`). Lost: agent-work VM 200, `st browser` (VM 100; local Chrome is the fallback), portfolio-ai and jobinator (VM 180), labs, ominull-hub, opencanary, restic-append. | Same. Notes keep working from sidarli's copy, and the phone Aico keeps working through the sidarli front door (see "two equal front doors" below). | **All dev is blocked**: no `st`, Agent Hub or tasks on sidarli. That's avoidable only with a Postgres replica on sidarli plus a manual promote, which is complex. |
| **sidarli off, gem on** | Household apps only, if VM 180 is on | Household apps, notes, capture, the phone Aico, a root rescue session on gem, and plain harness sessions in VM 200 (see "Remote agent work" below) | Light dev and hunting in one VM at a time |

Recommendation: do phase 1 with two equal Aico front doors. Leave phase 2 out for now. It swaps one single point of failure for a worse one, because gem being down would block all dev.

### Phone Aico when either host is down (owner question 2026-11-02)
Before this change, the phase 1 plan meant the main phone Aico was down whenever gem was. Revised design, **two equal front doors**:
- **Same app on both hosts:** aico-web and Tether run on both, from the same build. Each Tether links to the other host's Tether, so either front door shows every session. Each host has its own synced copy of the notes.
- **One tunnel with a connector on each host:** `aico.summitflow.dev` gets its own Cloudflare tunnel, with a `cloudflared` replica on each host. Replicas fail over when a host disappears. They don't steer traffic: a request goes to whichever connection is closest, so either one may serve it. That only works because both front doors are equal. This costs nothing; Cloudflare Load Balancing, which can steer and health-check, is paid and not needed.
- **What breaks with one host down:** with gem down, terminals and notes still work. With sidarli down, notes and capture still work, and the workstation's terminals show as offline.
- **Why Aico needs its own tunnel:** the workstation's tunnel serves about 15 hostnames (port, dev, aico, agent, neri, nightshift, approve and more). A replica of *that* tunnel on gem would get traffic for all of them.
- **aico-web state per server (checked 2026-11-02):**
  - **Tabs and seen times:** each server keeps its own in `~/.local/state/aico/web.db` (`panes`, `session_links`, `session_seen`, `project_settings`). Either sync them with the notes rows or accept that tabs differ per door.
  - **Uploads:** they go to the local disk, or over SSH to the session's host. That's fine.
  - **Duplicate pushes:** each process tracks asks and shows in memory (`asks.ts:188`, `shows.ts:114`), so two doors would push twice. Only the door whose Tether owns the session sends the push.

### Remote agent work with the workstation down (owner question 2026-11-02)
What exists, added after the October lockout:
- **Rescue kit on gem:** `/root/RESCUE.md`, `wake-ws`, `/root/rescue/`, and claude and codex in `/root/.local/bin`.
- **Watchdogs:** Nightwatch's break-glass probe, and the deadman off-host push.
- **Ways in:**
  - Door A: Ominull Terminal at `omi.summitflow.dev`, which needs the workstation.
  - Door B: the Proxmox UI at `pve.summitflow.dev`, through gem's own tunnel `9483e71c`. It works without the workstation.
  - `RESCUE.md:19` still says "once its Cloudflare app exists". Fix that line.

Adding the gem Aico front door gives the phone:
- **A root rescue session on gem** (claude, codex, `ssh ws`, `wake-ws`). It's easier than the Proxmox shell on a phone, and the Proxmox UI stays as the fallback.
- **Waking the workstation** (owner ask 2026-11-02). It's already possible: enp8s0 supports wake-on-LAN, set to magic packet and kept across reboots by netplan, and `wake-ws` on gem sends the packet. Per RESCUE.md it works after a shutdown but not after a power cut. Today the route is `pve.summitflow.dev` → Shell → `wake-ws`. With the gem front door, the workstation link in gem's `~/.config/tether/hosts.json` gets `wake-ws` as its wake command, so phone Aico shows a Wake button on the offline workstation. For power cuts, set the BIOS "restore on AC power loss" option, or use the smart plug. **Live test (owner OK'd doing it later):** shut the workstation down, wake it from the phone, and time how long it takes to answer pings and for Aico to come back.
- **Both hosts down: router WoL? No (owner question 2026-11-02).** Waking from the router is technically possible: gem's nic0 and nic1 both support magic-packet WoL, and OpenWrt has a roughly 20KB `etherwake`. But with both hosts down, the request has no way to reach the router: it has no Cloudflare path, and cloudflared doesn't fit (see the router entry in the decisions log). GL.iNet cloud or Tailscale would add a way in that doesn't go through Cloudflare. WoL also doesn't help in the likely both-down cases: a power cut (the NIC has no standby power) or a hung gem (only a power cycle helps).
  - **Instead:** set gem's BIOS (Tianbei GEM10) to power on after AC loss (owner 2026-11-02: "Yes, I'll set it"). Then the existing smart plug turned off and on is the both-down remote button. gem boots, and its Aico shows the workstation with a Wake button.
  - **Where to trigger it:** the smart plug's app when both are down. The Wake button on the offline host's row in Aico when gem is up. The Nightshift deadman push ("gem silent") is the cue.
- **VM 200 agent-work sessions** through gem's Tether. The wake command is a local `qm start 200`, and VM 200 has claude, codex, pi and agy.
  - **Limit:** with no workstation there is no `st`, Agent Hub or SummitFlow, so these are plain harness sessions in git checkouts.
  - **Worth adding:** VM 200 pulls fresh checkouts from GitHub, read-only. The Nightshift "workstation silent" push links to the Aico rescue session.

### Leftovers from moving portfolio-ai and jobinator to VM 180 (done 2026-11-02)
- **VM 180 has its own tunnel** (`cdd3c8b5`, remote-managed, token on the VM), so `port.` and `jobs.` never went through the workstation's tunnel `2757c3c8`. The workstation rules were stale, not live 502s.
- **Removed on the workstation:**
  - the `port.` and `jobs.` ingress from `/etc/cloudflared/config.yml` and the matching Caddy vhosts. Backups are `*.bak.20261102T165118Z`, both services were reloaded, and the other hostnames still answer.
  - the three disabled `jobinator-4000-*` user units
  - the pre-move local release builds under `~/.summitflow/services/projects/{portfolio-ai,jobinator-4000}/releases` (8.7G, rebuildable). The deploy receipts were kept as history.
- **Already correct, left as is:**
  - The SummitFlow `projects` rows: public URLs are `port.`/`jobs.`, and the ports match what VM 180 really listens on (3000/8000, 3014/8014). `st service status` shows both on VM 180.
  - The `portfolio` project row: that's your separate portfolio-site project, not a leftover.
  - The `portfolio-prod-api`/`db` sockets, which are live forwards to the VM.
- **Fixed:** the jobinator doc (`docs/project-guide.md`, commit 6148dd2).
- **Left alone:** the disabled project `backup_sources` rows. That's backup config, so it's your call; they're harmless while disabled.
- VM 180 was started for the check and shut down again.

## agent-hub
| # | Item | Status | Size |
|---|---|---|---|
| A1 | Delete `backend/scripts/run_claude_orchestrated_worker.py` (1,470 lines) and `backend/tests/scripts/test_run_claude_orchestrated_worker.py` (1,107) | Decided | -2.6k |
| A2 | Delete the unreachable runtime-context frontend files (useRuntimeContext, LibraryPane, RenderedPane, BlockRow...). Keep ContextManager and PolicyModal, which are live. Re-checked live. | Proposed | -2.6k |
| A3 | Remove the duplicate Codex protocol JSON copy in packages/agent-hub-client, and keep only the protocol versions still in use | Proposed | up to -11k (JSON) |
| A4 | Move docs/audits and docs/evaluations out of main. Nothing in the code references them. | Proposed | -50k (docs) |
| A5 | Squash the alembic migrations (278 files, 23k lines) and stop writing model-catalog updates as migrations. Needs a tested backup and an `alembic stamp` on the production database. | Proposed | about -20k |
| A6 | Dead backend modules and one-time backfill scripts, checking each file before removing it | Proposed | about -1.2k |
| A7 | Trim the giant mock-heavy test files and add tests for the subscription collector | Proposed | -3-4k tests |
| A8 | **Done 2026-11-02** (agent-hub b7ce9704a, deployed): deleted the review agent, governance, redundancy, lifecycle_score, tier ops, the memory analytics layer, their 3 schedules, 5 API routes and the dashboard Analytics tab. That's 80 files, -9.4k lines including tests. Kept the injection and search core, `/api/complete` with its metrics writer, and `st memory`. Live: backend healthy, fresh prompts still get memories (`context_deliveries`), and the gate went from 117s to 110s, now under its 113s budget. Follow-ups: (a) **Done 2026-11-02, your yes** (agent-hub acda326, migration e6a1c4d9b207, deployed): dropped `memory_review_runs` (276 rows) and `tier_change_log` (11,260 rows), the two `lifecycle_score` columns on `memories`, and the 2 disabled schedule rows, after a Drive backup from that morning. The 483 memories are untouched, and fresh prompts still get memories. The stale lifecycle badge in the memory UI went with the column. `memory_revisions.lifecycle_score` stays as an empty old column. (b) Fixed: `/api/memory/timeline` failed on every memory, because the code hardcoded `source="text"` (agent-hub f6dfd27, deployed). (c) Orphans: `agent_output_ingest.py`, `episode_operations.py`. | Done | -9.4k |
| A9 | Checked 2026-11-02: not a bug. `memory_injection_metrics` is written only on Agent Hub's own `/api/complete` path, and that path's traffic stopped on 10-30 (254 requests on 10-29, 4 on 10-30). Harness deliveries go through `build_canonical_context_delivery` and are recorded in `context_deliveries` (since 11-01). A live `st complete` wrote a new row. Fold into A8: point the memory dashboard and analytics at `context_deliveries`, or drop them with the analytics layer. | Done (no change) | 0 |

## summitflow
| # | Item | Status | Size |
|---|---|---|---|
| S1 | Remove `st claude` (`backend/cli/commands/claude.py`, `_claude_dispatch.py`, `backend/tests/cli/test_claude.py`), its registration and its help and capability text | Decided | -0.9k |
| S2 | Fix the `test_guard_corpus.py` fixture so it is built once, not once per worker. It starts about 3.9k subprocesses. | Proposed | about -9s check time |
| S3 | Delete `experiments/system-monitor`, which host-monitor superseded | Proposed | -1.8k |
| S4 | Dead backend and frontend files; mockup ratings and comments (0 rows in the database) | Proposed | about -1.4k |
| S5 | Re-baseline the 77 alembic migrations | Proposed | -4.7k |
| S6 | Low-use `st` commands: critique (1 mention in 90 days), ready-all (7), exec-log (12), sync-progress (27). The counts are mentions, so confirm real runs before cutting. | Proposed | about -1.4k |
| S7 | Clean `.git/st/acceptance/isolated-observations`: 6.0G of state that `st` regenerates | Proposed | disk |
| S8 | **Gap found 2026-11-02:** `st check --quick`, which `st commit` runs, never type-checks a repo's nested TypeScript projects. In Aico that's `tether`, `web/server` and `web/frontend`; only the full check's native stages cover them. A real type bug in the photo reader got past commit and was caught only by `st check --check`. Fix: let a native `check` stage opt into the quick lane (e.g. `quick = true`), and turn it on for aico's three `tsc` stages, about 5 s together. Check other repos with nested `tsconfig`s too. | **Done 2026-11-02.** A native `check` stage can set `quick = true` (optional `quick_paths` globs limit it under `--changed-only`); `st check --quick` runs those after the legacy tools as `NATIVE:OK/FAIL:<id>` with a details file. Aico's three `tsc` stages opt in for `**/*.ts, *.tsx, *.mts, *.cts, *.json` (web/server imports tether source, so the paths are repo-wide). Live proof: a type error in aico web/server/src/api.ts made `st check --quick --changed-only` fail, passing again after revert. Gate cost: the three stages add 2.4 + 1.1 + 1.5 = 5.0 s to a quick run that touches TypeScript, nothing otherwise; `st check budget` in aico reads 101 s before and after (it is a median of past runs). Commits: SummitFlow 2a4369478, aafd0e229, 74b35c1f3; aico 3e475e80b. Other repos: no nested `tsc` native stages; a-loom `apps/aloom-ui` is not covered by quick (its root tsconfig only includes vite.config.ts) and would need a stage first. Checked by me 2026-11-02: aico's three stages are live in the quick lane. Follow-up, small: agent-hub `packages/*` (chat-ui, notes-ui, passport-client, agent-hub-sdk) and a-loom `apps/aloom-ui` have their own tsconfigs that the quick lane doesn't check. Code they share with the main app is checked through it, but code only inside them isn't. Add the same stages if those packages see regular changes. | small; gate +5 s |

## aico
| # | Item | Status | Size |
|---|---|---|---|
| C1 | Delete `tether/src/lifecycle/native-admin.ts` and its test, `qualify-codex-admin.py` and the qualification JSONs. Only docs reference them. Re-checked live. | Proposed | about -1k |
| C2 | Collapse the pane/tab/slot hook chain left over from multi-pane | Proposed | -1-1.5k src, -1.5k tests |
| C3 | Trim tests that read source text or rely on heavy mocks. Test lines grew by 10.3k recently. | Proposed | -3-4k tests |
| C4 | Split `tether/scripts/aico-root-watch.py` (3.2k lines, 86 commits in 90 days) and `lifecycle/engine.ts` (3.3k), and add tests for `engine.ts` and `daemon.ts` | Proposed | 0 net |
| C5 | Keep `tether-lifecycle-harness.sh` and `tether-real-session-smoke.sh` (the only live proof that Tether contains its processes) and run them in the nightly deep lane. Deleted `aico-install-context-hooks.sh` (aico b4a9c00). Both scripts now run in the nightly deep lane against a throwaway `tether@dev` (aico bdcc2a6). The first deep run passed: 13 harness checks and the Codex smoke, with nothing left behind. | Done | -23 lines |

## nightshift
| # | Item | Status | Size |
|---|---|---|---|
| T1 | Parallel tests (xdist) and a look at the 13 autouse fixtures. Tests take 48s on their own, but the check takes 110-154s. | Proposed | check time |
| T2 | Remove the file-vs-store comparison (`items/diff.py`, `shadow.run_diff`). It still runs every 15 minutes after the migration finished. | Proposed | -1-1.8k |
| T3 | Fold `decide/` into `rules.py`; the module itself says nothing there learns. Collapse ingest schema versions v1-v4. | Proposed | -0.9-1.5k |
| T4 | ~~Tray just opens the PWA~~. Withdrawn: on 10-30 you moved to the native inbox panel. Data comes from shared `nightshift inbox --json`, with parity tests (`tests/test_inbox.py`); only the drawing is duplicated. | Withdrawn | 0 |
| T5 | Keep the ledger (hash chain, checked every 15 min, anchored on PVE) and the drill (monthly). Fixed 2026-11-02 (nightshift debbe2d). The tripwire marked a declared listener as "traced" when the same 15-minute pass also had other agents' listeners closing. Declared listeners now count as declared first. Regression tests were added, it's deployed, and a live listener drill passes. | Done | 0 |

## neri
| # | Item | Status | Size |
|---|---|---|---|
| R1 | Delete `proxy/ops/synthetic` and `backend/scripts/import_index.py`. Nothing references them. Re-checked live. | Proposed | -564 |
| R2 | Keep all exit kinds. The live config uses `direct`, `warp` (free Cloudflare WARP) and `oracle` (WireGuard to an Always Free Oracle VM). `platform-vpn` has no tooling, but it backs the 10-31 safety rule: a program with `rules.vpn_required = true` is refused unless a platform-vpn exit is configured (`proxy/neri_proxy/exits.py:51-69`). | No change | 0 |
| R3 | Merge `proxy/ops/live/live_check.py` into the selftest | Proposed | about -300 |
| R4 | Split `st_cli/commands.py` (2.2k lines) and `hunt_cmd.py` (2.0k); add tests for `sandbox_root.py` and `addon.py` | Proposed | 0 net |

## Execution order
0. This plan is the record; keep it current.
1. Quick cleanups. **Done 2026-11-02:** C5 hooks wrapper, T5 drill listener, A9 check, RESCUE.md line 19 (nightshift 216a0d9, and installed on gem), and the VM 180 leftovers. 
2. A8: the dormant memory layers. **Done**, including the dormant tables (agent-hub acda326).
3. Vision bake-off. **Done 2026-11-02:** agy `gemini-3.8-flash-low` wins (see Vision). Local qwen3-vl is the fallback.
   - **Milestone 2 (background photo reader) shipped 2026-11-02** (aico f935861, 8fa745d, c5e73e6, af4f65f; deployed). New captures are read in the background, 15-40 s per photo, two at a time. The detail page shows the reading right under the picture: list items with your spelling beside a cleaned-up name, receipt lines and totals, the odometer. Couldn't read it gets a Retry, and `tether capture result ID` gives agents the result. agy reads PDFs and voice recordings directly, so no separate speech-to-text is needed. Checked live by me on your odometer photo (33396, trip 44.6) and your grocery list. The test captures were deleted. **Limit:** the model still sometimes marks an underlined item as crossed out (bread crumbs), even after a prompt fix that got sea salt right. So in Milestone 4, items from a photo go onto a list unchecked, with crossed-out shown only as a hint. Still to do: install and sign in `agy` on gem (Milestone 6); the ollama fallback reads pictures only.
   - **Milestone 3 (sending captures on) shipped 2026-11-02** (aico b532461, deployed). Which type goes where is a data file (`web/server/capture-types.default.json`). Receipts get Send / Not a receipt / Keep here, plus one tray todo. Send hands the receipt to portfolio-ai and deletes Aico's copy. With VM 180 off it waits and retries on the 15-minute maintenance pass, or on Send now. Notes types wait for Milestone 4, and car types say vehicles come later. Checked live with VM 180 off (waiting) and on (health and auth through the forwarder). The real hand-off wasn't run, because portfolio-ai already holds that Costco receipt, imported as a PDF on 2026-08-22, and a duplicate shouldn't be filed. VM 180 is back off. **Found:** the portfolio-prod forwarders ssh to `apps.lan`, but the workstation's local DNS doesn't answer `.lan` names. `~/.ssh/config` now maps `apps.lan` to 192.168.86.160. That's a fixed reservation on the router (`dhcp.apps_180`), so it's stable.
   - **Milestone 4a (notes server) shipped 2026-11-02** (aico 5bcbe2e, deployed). Notes, lists, labels, attachments, edit history and search are in, plus `tether note` for agents. A grocery-list photo now files itself into Groceries: items are added unchecked, the ones crossed out on the photo get a hint, and the photo is attached. Retrying never duplicates items. Checked live by me (the Groceries list is there and empty). The phone screens are Milestone 4b, being built now.
   - **Bugs found 2026-11-02, fix in progress:** your Needs you answers could vanish without reaching the asking session (they were held while it was busy, then lost across a Tether restart). And a photo ask could be answered without its photos. What you asked for: answers needn't interrupt, but they always arrive, at the latest with the session's next turn.
   - **Fixed 2026-11-02** (aico 9909e79, 89f4a44, ea4600a; deployed, proven live in a test session). *Real cause of the lost answers:* Claude Code reports a session as busy for as long as it waits on background agents, so Tether held the answers. My own `ask done` then deleted them unread; the restart wasn't the cause. Now an answer comes in with the session's next turn even while it's busy, survives restarts, and is queued while Tether restarts. Every held or dropped answer is logged with the reason. A photo ask can't be answered below its minimum: the server refuses it, the card says "Add 2 more photos", and the "Answer without files" button is gone. A failed upload shows on the card, and refused uploads are logged. Not settled: why your phone test sent no photos. None reached the server. Either an upload failed without the card showing it, or the old "Answer without files" button was tapped.
4. Notes store, capture and the two Aico front doors: a design doc first (`aico/docs/plans/notes-and-capture.md`), then build. **Milestone 1 is Capture v1:** a Capture button anywhere in the phone PWA that opens the camera and stores photos durably, plus a captures list and an agent read path. It moves ahead of the bake-off, because the bake-off photos are taken with it. Design written: `aico/docs/plans/notes-and-capture.md` (aico 6bad3ed). It has nine milestones, puts gem's copy in a new LXC (CT 190), runs sync over the existing tether-link SSH, and keeps the Wake button aside until you OK it. **Milestone 1 (Capture v1) shipped 2026-11-02** (aico ff537f7 server and CLI, b1eb688 frontend; deployed with the Tether CLI). The Capture button sits next to Needs you, with Take photo and Choose files (multi-select), a Captures list and detail, and `tether capture list|get|file`. Checked live in a headless phone-size browser; a real iPhone photo, HEIC and Safari are still to be tried on your phone. HEIC previews are full-size for now (no resize). **Milestone 1b (file requests in Needs you) shipped 2026-11-02** (aico f24df3e Tether v30, 45d2c55 server, 11267d8 card; deployed). `tether ask create ... --files MIN-MAX --files-hint`, with the card's Take photo and Choose files. The answer reaches the asking session with capture ids. Checked live at phone size. The bake-off photos were requested this way. **1b (owner 2026-11-02): photo requests in Needs you.** `tether ask create ... --photos N` adds a Take photo / Choose files control to the ask card. Both entry points take fresh photos or existing photos and files equally, with multi-select: images including HEIC, PDFs such as service invoices, and documents. The photos are saved as captures tagged with the ask, and the answer reaches the asking session with their capture ids. The bake-off photos are requested this way.
   - **Fixed 2026-11-02 (aico 11458fa):** on your phone, Choose files couldn't pick several photos. It closed and uploaded on the first tap, because Android opens its document chooser when the list mixes photos with PDFs. Phones now get three buttons: Camera, Photos (Android's own photo picker, where taps pick several) and Files.
5. Vehicles in portfolio-ai.
The rest of the per-project items (Proposed) follow, each verified with `st check`, and with `st check budget` timings before and after.
