# st CLI Output Formats

## Output Modes

| Flag | Output |
|------|--------|
| (default) | Compact single-line JSON |
| `--human` | Pretty-printed JSON (indent=2) |
| `--compact` | TOON-style one-liner per item |

---

## Compact Format Specs

### st ready --compact
```
READY[3]
P1 task-2cbb08e9 feature pending  Create supervised autonomous testing...
P1 task-5fbb450e feature pending  Implement test project infrastructure...
P2 task-c1623ab5 feature running  Context Efficiency Optimization
```
Format: `P<priority> <id> <type:7> <status:7> <title:50>`

### st list --compact
```
TASKS[15]
task-xxx P1 feature running Title here...
task-yyy P2 bug     pending Another title...
```
Format: `<id> P<priority> <type:7> <status:7> <title:40>`

### st show --compact
```
task-c1623ab5|running|P2|feature|2/20 subtasks|Context Efficiency Optimization
```
Format: `<id>|<status>|P<priority>|<type>|<done>/<total> subtasks|<title>`

### st subtask list --compact
```
SUBTASKS[20]:2/20:10%
2.1 PASS Backup pre_it.md [2/2]
2.2 PASS Condense pre_it.md [4/4]
2.3 ____ Verify pre_it.md functionality [0/4]
5.1 ____ Design --compact formats [0/10]
```
Format: `<subtask_id> <PASS|____> <description:40> [<done>/<total>]`

### st subtask list --progress-only
```
SUBTASKS:2/20:10%
```
Single line summary only.

### st step list --compact
```
STEPS[4]:0/4:0%
1 ____ Task agent comparison vs backup
2 ____ Fix any missing functionality
3 ____ Delete backup
4 ____ Commit changes
```
Format: `<step_number> <PASS|____> <description:50>`

### st dep list --compact
```
DEPS[3]
task-xxx blocks task-yyy
task-aaa after  task-bbb
```
Format: `<from_id> <type:6> <to_id>`

### st capability list --compact
```
CAPS[5]
memory-system       tests:4 status:ready
task-execution      tests:2 status:ready
```
Format: `<id:20> tests:<n> status:<status>`

### st component list --compact
```
COMPONENTS[8]
backend/api         files:12
frontend/components files:8
```
Format: `<path:25> files:<n>`

---

## Design Principles

1. **One line per item** - Minimal vertical space
2. **Fixed-width fields** - Scannable columns
3. **Header with count** - `TYPE[N]` shows total immediately
4. **Progress in header** - `SUBTASKS[20]:2/20:10%` for quick status
5. **Truncate long strings** - Titles capped at 40-50 chars
6. **PASS/____ for boolean** - Visual scan for incomplete items

---

## Implementation

Add to `cli/output.py`:
- `_compact_output: bool` module flag
- `set_compact_output(enabled: bool)`
- `format_compact_task(task) -> str`
- `format_compact_subtask(subtask) -> str`
- `format_compact_step(step) -> str`
- `output_tasks_compact(tasks, header="TASKS")`
- `output_subtasks_compact(subtasks, task_id)`
- `output_steps_compact(steps, subtask_id)`

Add to `cli/main.py` callback:
- `--compact` flag sets `_compact_output = True`

Each output function checks `_compact_output` and calls appropriate formatter.
