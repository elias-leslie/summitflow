

## Xterm.js Initialization and Font Loading

Synchronize xterm.js initialization with browser font loading for 'JetBrains Mono' to prevent character width calculation errors. This prevents rendering bugs and garbled characters in the 'Phosphor Terminal' aesthetic.

*Rationale: Identified as a root cause for rendering bugs in the terminal redesign plan.*

<!-- Pattern ID: 6b165f40-ca6b-40e3-a20b-374228c2d2fd | Applied: 2025-12-29T14:12:56.286318 -->

## Terminal Database Configuration and Maintenance

Use database 'summitflow' and user 'summitflow_app' for terminal operations. When updating backup or restore scripts, specifically include the 'terminal_sessions' table and use 'numfmt --to=iec' for human-readable size reporting.

*Rationale: Consistent database parameters and table names were used across restore and backup script updates in session 385f4b04.*

<!-- Pattern ID: e5a3cedd-4086-4c78-8a6f-9d764a79adc1 | Applied: 2025-12-29T14:12:56.325332 -->
