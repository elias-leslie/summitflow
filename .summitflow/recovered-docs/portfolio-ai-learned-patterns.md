# Learned Patterns

This file contains patterns automatically learned from successful agent sessions.

**How patterns are learned:**
1. Session diary entries are analyzed via reflection
2. Successful approaches are extracted as patterns
3. High-confidence patterns (>0.7 confidence) are auto-approved
4. Patterns are applied at session start for context

**Managing patterns:**
- Patterns can be approved/rejected via the `/api/memory/patterns` API
- Delete pattern blocks to remove them permanently
- Edit patterns directly to refine their guidance

---



## Invalidate all watchlist caches together

Use `invalidate_all_watchlist_caches()` to invalidate all Redis symbols and HTTP response caches for watchlist instead of individual invalidation. Example: `invalidate_all_watchlist_caches(watchlist_id)`

*Rationale: Simplifies code, ensures consistency and improves maintainability in watchlist cache invalidation.*

<!-- Pattern ID: 2d9145e3-77b5-4853-bc4e-153efb62ba96 | Applied: 2025-12-28T16:20:32.922817 -->

## Avoid hardcoded Tailwind colors

Do not use hardcoded Tailwind CSS color classes directly in components. Use semantic design tokens instead.  Example: Instead of `text-green-500`, use a theme-aware color class defined in the design system.

*Rationale: Hardcoded colors violate design token constraints and make it harder to maintain consistent styling.*

<!-- Pattern ID: 8e95fdaa-271a-4fa7-8dd9-c376d4b4ee81 | Applied: 2025-12-28T16:20:32.962005 -->

## Use semantic design tokens for UI styling

Replace hardcoded Tailwind CSS colors with semantic design tokens to ensure UI consistency and maintainability. Example: Replace `text-yellow-600` with `text-warning`.

*Rationale: Migration to semantic tokens ensures UI remains consistent with the application's design system and enables easier theme management.*

<!-- Pattern ID: ad86d156-072e-46eb-962b-e07e76678401 | Applied: 2025-12-28T16:20:32.999354 -->

## Prefix intentionally unused variables with an underscore

To satisfy linter/compiler constraints while maintaining clean code, prefix intentionally unused variables with an underscore. Example: `const _myUnusedVariable = someValue;`

*Rationale: This approach silences linter warnings about unused variables without removing them, which is necessary when the variables are required by external callers.*

<!-- Pattern ID: 350516dc-fdb1-4067-882f-294b74192bf7 | Applied: 2025-12-28T16:20:33.036468 -->

## Grant SELECT permissions on tables to view owners in PostgreSQL

When a PostgreSQL view owned by `user_a` accesses tables owned by `user_b`, grant `user_a` explicit `SELECT` permissions on those tables using a migration script. Example: `GRANT SELECT ON table_name TO user_a;`

*Rationale: PostgreSQL views run with the view owner's permissions, not the invoker's. Failing to grant permissions results in 'permission denied' errors.*

<!-- Pattern ID: 0d451def-b372-4440-a660-e0e331467fa9 | Applied: 2025-12-28T16:20:33.074609 -->

## Extract token and truncation constants in backend base agent

In `backend/app/agents/base.py`, define and use constants `MAX_LLM_TOKENS`, `TOOL_RESULT_TRUNCATE`, and `RESULT_SUMMARY_LENGTH` instead of hardcoding values in the processing logic.

*Rationale: Extraction of these constants in session 1ca98a40 improved maintainability and was verified by 108 passing agent tests.*

<!-- Pattern ID: 94e85208-4f62-470d-aff5-5ddaa82b2931 | Applied: 2025-12-28T21:23:32.175177 -->

## Exclude node_modules from frontend file searches

When using `find` or `grep` to analyze frontend files, always exclude the `node_modules` directory. Use a command like `find frontend -not -path '*/node_modules/*' -name '*.tsx'` to ensure results reflect project source code, not dependencies.

*Rationale: An analysis task failed to accurately identify large project files because results were dominated by large dependency files in node_modules.*

<!-- Pattern ID: 2775f0fb-4ea4-4fd0-9613-13e61240031e | Applied: 2025-12-28T22:26:54.606370 -->

## Abstract database access using Repository and Storage patterns

Use abstractions like `get_strategy_storage()` or Repository classes for data access instead of executing raw SQL directly within business logic or Celery tasks. Move SQL queries to dedicated methods such as `get_symbols_needing_strategies` or `get_underperforming_strategies` within the storage layer.

*Rationale: Session 0f4f71ff demonstrates the successful decoupling of SQL queries from task logic to improve modularity and testability.*

<!-- Pattern ID: 7a0ef3cd-d3ce-4b1e-ab6a-4a39663cea48 | Applied: 2025-12-29T08:35:30.446337 -->

## Restrict implementation.json updates to 'passes' field

When updating `implementation.json` during the refactor-it project, strictly limit modifications to the 'passes' field. This ensures the implementation plan integrity is maintained while tracking progress.

*Rationale: Enforces a highly structured workflow for parallelizable task execution.*

<!-- Pattern ID: 7d914d6a-3b73-4e30-b468-eef29fa7b6b6 | Applied: 2025-12-29T14:33:31.957510 -->

## Use atomic commit format for refactor-it tasks

Format commit messages as `feat(refactor-it): task X.Y - <description>` for the parallel optimization project. Ensure each commit corresponds to a single completed task from the implementation plan.

*Rationale: Establishes a structured workflow and clear project history for multi-phase optimization efforts.*

<!-- Pattern ID: c197f55a-a7c2-49b3-956d-801891e103dc | Applied: 2025-12-29T14:33:31.997974 -->

## Document pre-existing failures during task verification

When verifying tasks with `npm run lint` or backend tests, explicitly identify and document pre-existing failures in unrelated modules. A task passes if the specific changes are verified and no new regressions are introduced.

*Rationale: Prevents blocking progress on technical debt reduction when unrelated components have pre-existing issues like lint warnings or missing imports.*

<!-- Pattern ID: 662589f9-ce19-4929-a007-21d2d2a8f701 | Applied: 2025-12-29T14:33:32.037358 -->

## Use centralized URL utilities for backend connections

Import `getServerUrl` and `getWsUrl` from `@/lib/server-url` for all backend communication. Replace manual WebSocket conversions like `url.replace(/^http/, 'ws')` with `getWsUrl(url)` to ensure consistent protocol handling.

*Rationale: Centralizing URL logic reduces duplication and ensures environment-based resolution remains consistent across components like AgentPanel and DevAssistantPage.*

<!-- Pattern ID: 88dfd1dc-b615-4b13-9dc3-0712d7fbf81a | Applied: 2025-12-30T09:40:00.327476 -->

## Use ellipsis in type hints for variable-length database tuples

Use `list[tuple[Any, ...]]` as the return type hint for database repository methods like `get_market_trends_data` or `get_indicator_history_data`. This accurately reflects that database rows may contain an unspecified number of elements and improves static analysis.

*Rationale: Observed in session 23c8a230; fixed type mismatches when database queries return more or fewer columns than a fixed-length tuple expects.*

<!-- Pattern ID: 6daecb88-65ca-40d6-9574-b301a0c483b1 | Applied: 2025-12-30T15:37:14.746649 -->

## Validate market events against VALID_EVENT_TYPES constant

Import and use the `VALID_EVENT_TYPES` constant from the market API module to validate economic events. Supported types are: `['fed_speech', 'fomc_decision', 'gdp_release', 'pce_release', 'nfp_release', 'cpi_release']`.

*Rationale: Explicit validation was implemented to replace unsafe type casting and ensure runtime reliability for market intelligence tasks.*

<!-- Pattern ID: 4249ded0-b4dc-49e3-8f58-062b19444175 | Applied: 2025-12-31T09:20:32.969417 -->

## Use require_nonempty_df for DataFrame validation in APIs

Use the utility function `require_nonempty_df(df, symbol)` in watchlist and market API endpoints instead of manual emptiness checks like `if df.is_empty(): raise HTTPException`. This ensures consistent error responses and reduces boilerplate in the API layer.

*Rationale: Observed in multiple successful refactoring steps to standardize resource validation across the portfolio-ai backend.*

<!-- Pattern ID: ed2cd18e-bff3-41fa-b67b-4733ca756404 | Applied: 2025-12-31T09:20:33.006480 -->

## Use _create_intraday_refresh_tasks helper for Celery chains

In `backend/app/celery_schedules.py`, use the `_create_intraday_refresh_tasks` helper function to generate consistent sequences of dependent tasks. The standard sequence is: `refresh_daily_ohlcv` -> `populate_fear_greed_inputs` -> `calculate_fear_greed`.

*Rationale: Introduced to improve modularity and ensure consistent staggering patterns across morning, midday, and after-close market data refreshes.*

<!-- Pattern ID: 0a3da676-2461-481c-9597-42572cc0b403 | Applied: 2025-12-31T10:35:09.438057 -->

## Use PortfolioStorage in market transformers

In backend/app/transformers/market_transformers.py, replace all imports and usages of BaseStorage with PortfolioStorage. This ensures the transformer uses the correct specialized storage interface for market data.

*Rationale: Entry 518ec561 shows a fix where replacing BaseStorage with PortfolioStorage was required to resolve type/runtime errors in market_transformers.*

<!-- Pattern ID: 9ddfb7cb-80bf-4010-a738-e411be140d40 | Applied: 2025-12-31T17:42:28.781982 -->

## Use ISO strings for scan timestamps in TypeScript

Define timestamp fields in TypeScript interfaces as `string` (ISO 8601 format) rather than `number` when consuming scan data from the explorer API. This aligns the frontend types with the actual API data structure.

*Rationale: Fixes type errors where the frontend expected a number but the API returned an ISO string.*

<!-- Pattern ID: 57e75140-a7d0-40a0-819d-58b56c579ef2 | Applied: 2025-12-31T18:48:22.912022 -->

## Match frontend status checks to API 'completed' and 'failed' values

Update frontend status checks to use 'completed' and 'failed' instead of 'complete' or 'error'. This ensures compatibility with the API's status reporting for background tasks like file scans.

*Rationale: Directly observed a mismatch between frontend expectations and API reality in the SummitFlow project.*

<!-- Pattern ID: f30cc927-c19f-4b70-a292-8e97b936eca5 | Applied: 2025-12-31T18:48:22.954833 -->

## Use _calculate_cutoff_timestamp for cleanup tasks

Replace inline cutoff time calculations in log and temp file cleanup tasks with the centralized `_calculate_cutoff_timestamp` helper function. This applies to `cleanup_old_logs_task`, `cleanup_temp_files_task`, and `cleanup_solution_state_task` within the log cleanup module.

*Rationale: Reduces technical debt and ensures consistent timestamp logic across different cleanup processes.*

<!-- Pattern ID: f4bf6cb9-5d52-4a62-bb41-a4c3c2b7f56b | Applied: 2025-12-31T18:48:22.990939 -->

## Use _extract_output_tokens in base agent

In `backend/app/agents/base.py`, use the `_extract_output_tokens` helper method to extract token counts from LLM outputs. This ensures consistent token usage tracking and metadata extraction across all agent subclasses.

*Rationale: Refactoring task 5.1 successfully extracted this logic into a reusable helper for the base agent.*

<!-- Pattern ID: 687863f6-0d87-480e-8b1d-b8d40a4cffec | Applied: 2025-12-31T20:56:58.162674 -->

## Use _filter_symbols_without_active_strategy for monitoring

In strategy monitoring tasks, use the helper method `_filter_symbols_without_active_strategy` to isolate symbols requiring new strategy generation. This replaces inline loops and centralizes filtering logic.

*Rationale: Identified as a successful refactoring (Task 5.2) to improve modularity in backend strategy tasks.*

<!-- Pattern ID: e87b5871-e4dc-4c62-a86f-71ca201bae9a | Applied: 2025-12-31T20:56:58.205393 -->

## Use truncated debug logging for parse failures

When logging parsing errors in `parse_journal_output`, use `logger.debug('journal_entry_parse_failed', error=str(e), line=line[:100])`. This captures the error and enough context for debugging without bloating logs with large strings.

*Rationale: Observed as a successful pattern in session 3cc4cb2f for improving observability without performance cost.*

<!-- Pattern ID: 5a839021-398d-4f49-9064-98b8fe16b123 | Applied: 2025-12-31T20:56:58.240843 -->

## Import JSON logger from pythonjsonlogger.json

Use `import pythonjsonlogger.json` instead of the deprecated `pythonjsonlogger` path. This prevents deprecation warnings and potential failures in the backend logging suite.

*Rationale: Test suite execution revealed dependency warnings indicating the module path has moved.*

<!-- Pattern ID: 875a8548-6739-4a90-b1f9-0914fd1a6937 | Applied: 2025-12-31T23:32:14.434989 -->

## Use performance constants in get_underperforming_strategies

Use `DEFAULT_PERFORMANCE_THRESHOLD` and `PERFORMANCE_WINDOW_DAYS` constants in the `get_underperforming_strategies` method. Avoid hardcoding these values directly in SQL queries or business logic.

*Rationale: Implemented during task 1.3 of the strategy logic refactor to centralize threshold management.*

<!-- Pattern ID: 3cc69a38-b8f1-40b5-9d01-abca2fb5b5ac | Applied: 2025-12-31T23:32:14.476546 -->

## Use safe_send_json for WebSocket communication

Use `await safe_send_json(websocket, message)` for all server-to-client messages. This pattern ensures robust handling of bridge states and prevents serialization errors from crashing WebSocket connections.

*Rationale: Extensive usage of this pattern was observed as a 'what worked' factor in the strategies and market APIs.*

<!-- Pattern ID: a7f9e9aa-f5a0-44ac-a451-8cce64d23b39 | Applied: 2025-12-31T23:32:14.513756 -->

## Use _substitute_path_params for dynamic URL construction

Use the helper function `_substitute_path_params(url_template, params)` to replace placeholders in dynamic API endpoints. This ensures consistent URL formatting for tool executions and internal API calls.

*Rationale: Identified as a successful implementation and usage pattern during a multi-phase refactoring session.*

<!-- Pattern ID: 0fc808e0-9e50-4ef8-8391-f232bf5dc106 | Applied: 2025-12-31T23:32:14.549779 -->

## Execute backend tests with fail-fast and short tracebacks

Run the backend test suite using `pytest tests/ -x --tb=short -q`. The `-x` flag ensures execution stops on the first failure, which is critical for efficiency when running the full 1,878-test suite.

*Rationale: This specific command was identified as the standard for backend validation in sessions aaa68418 and e6afc68b.*

<!-- Pattern ID: 71767c3f-239d-458e-b557-031d9208a171 | Applied: 2026-01-01T07:46:23.351947 -->

## Monitor long-running pytest executions via ps and wc

To track background pytest progress without blocking, use `ps aux | grep pytest` to verify the PID, and `wc -l <log_file>` combined with `tail -n 20 <log_file>` to monitor execution count and status.

*Rationale: Consistently used across multiple sessions (aaa68418, e6afc68b) to manage the execution of a 1,800+ test suite.*

<!-- Pattern ID: d3dc65bf-9f9e-400d-9261-1c2b38109c19 | Applied: 2026-01-01T07:46:23.386361 -->

## Use rows_to_dicts for database cursor result mapping

Use the `rows_to_dicts(cursor)` helper function to map PostgreSQL cursor results to a list of dictionaries. This utility automatically uses the cursor description to populate keys, ensuring consistency with database schema fields like `sharpe_ratio`, `start_date`, and `status`.

*Rationale: Verified as a successful pattern for database result handling in the portfolio-ai backend.*

<!-- Pattern ID: c20bd8f7-d497-4c20-9eb6-8617aaaf7aef | Applied: 2026-01-01T09:17:40.241716 -->

## Standardize Watchlist API with @handle_api_errors and helpers

Apply the `@handle_api_errors` decorator to all Watchlist API endpoints. Extract complex logic into helper methods like `_build_enriched_indicators` to improve type safety and ensure uniform error responses.

*Rationale: Recent successful refactoring of the Watchlist API established these patterns for consistency and error resilience.*

<!-- Pattern ID: 5b562145-c0ba-4e5c-a85e-9987040e8092 | Applied: 2026-01-01T11:54:51.307521 -->

## Offload synchronous service calls to threadpool in FastAPI

Use `from fastapi.concurrency import run_in_threadpool` to execute blocking service layer methods like `get_items_with_scores`. This architecture ensures that synchronous operations do not stall the asynchronous event loop.

*Rationale: Observed in Watchlist API analysis where blocking calls to the service layer were offloaded to maintain API responsiveness.*

<!-- Pattern ID: 97752884-dc8d-4550-a672-13cc61b88b4e | Applied: 2026-01-01T11:54:51.347863 -->

## Mandatory refactoring workflow and progress tracking

Follow the pre-task checklist: Read files, grep usages, Identify coverage, Risk level, Verdict. Track step-level progress via PATCH requests to http://localhost:8001/api/projects/${PROJECT_ID}/tasks/<task-id>/subtasks/<subtask-id>/steps/<step-number>.

*Rationale: Established in session 5237d554 to ensure systematic refactoring and automated dashboard synchronization.*

<!-- Pattern ID: 68f551cc-43d7-46d7-8f0f-4ef9db380dc5 | Applied: 2026-01-01T13:25:11.341394 -->

## Add vaderSentiment and pandas_ta to backend dependencies

Ensure the `vaderSentiment` and `pandas_ta` Python packages are installed in the backend environment. These libraries are necessary for sentiment and technical analysis features in the refactored market intelligence modules.

*Rationale: Missing dependencies were identified as the cause of failures during the recent API structure update.*

<!-- Pattern ID: c18057bb-eee8-4f07-be18-242caa71f779 | Applied: 2026-01-01T20:53:25.433427 -->

## Normalize URL paths with TrailingSlashMiddleware in FastAPI

Import and integrate `TrailingSlashMiddleware` in the FastAPI application entry point to ensure consistent handling of requests with or without trailing slashes. This prevents unnecessary 307 redirects and avoids 404 errors when requests are proxied without trailing slashes.

*Rationale: Resolved 404 errors and redirection overhead during backend-frontend integration tests.*

<!-- Pattern ID: 467c6dd7-5d22-4a25-8fe6-f8e05a51743d | Applied: 2026-01-01T20:53:25.467334 -->

## Install vaderSentiment and pandas_ta for backend analysis

Ensure that the `vaderSentiment` and `pandas_ta` Python packages are installed in the backend environment. These dependencies are required for sentiment and technical analysis logic in the portfolio-ai service.

*Rationale: Backend service failures were resolved by adding these missing analytical dependencies which are now integrated into the core backend functionality.*

<!-- Pattern ID: 156a8e6e-1f4b-4139-ad6f-9a38a70fec99 | Applied: 2026-01-01T20:53:25.502436 -->

## Normalize FastAPI URLs with TrailingSlashMiddleware

Add `TrailingSlashMiddleware` to the FastAPI application in the main entry point. This ensures that requests to paths with or without trailing slashes are handled consistently, preventing 404 errors in proxy environments and eliminating the latency of 307 redirects.

*Rationale: Direct backend testing showed that missing trailing slashes triggered 307 redirects or 404s when accessed through proxies. Normalizing the URLs at the middleware level ensures consistent routing.*

<!-- Pattern ID: 1539cf82-2c15-4826-bda9-c6c7b925512f | Applied: 2026-01-01T20:53:25.538601 -->
