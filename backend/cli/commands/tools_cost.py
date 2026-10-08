"""Read-only result accounting and bounded advice for the existing cost command.

Keep payloads and retrieval fingerprints in PostgreSQL; only aggregates leave it.
Call identity is session-local. Exact nested-command links are provenance, not
an additional delivery when their wrapper has a measured result.
"""

from __future__ import annotations

import json
from typing import Any

from psycopg import sql


def _result_ctes() -> sql.SQL:
    return sql.SQL("""
        WITH candidates AS (
            SELECT e.*,
                   COALESCE(NULLIF(e.call_id, ''), NULLIF(e.tool_output->>'call_id', ''),
                            NULLIF(e.tool_output->>'tool_use_id', '')) AS call_identity
            FROM session_events e
            WHERE e.event_type = 'tool_result'
              AND COALESCE(e.source_timestamp, e.created_at) >= now() - (%s * interval '1 hour')
              AND (%s::text IS NULL OR e.session_id = %s)
              AND NOT (
                  (e.source_event_id IS NULL OR e.source_event_id LIKE 'native-command:%%')
                  AND EXISTS (
                      SELECT 1 FROM session_events authoritative
                      WHERE authoritative.session_id = e.session_id
                        AND authoritative.event_type = 'tool_result'
                        AND authoritative.source_event_id IS NOT NULL
                        AND authoritative.source_event_id NOT LIKE 'native-command:%%'
                        AND COALESCE(NULLIF(authoritative.call_id, ''),
                                     NULLIF(authoritative.tool_output->>'call_id', ''),
                                     NULLIF(authoritative.tool_output->>'tool_use_id', ''))
                          = COALESCE(NULLIF(e.call_id, ''), NULLIF(e.tool_output->>'call_id', ''),
                                     NULLIF(e.tool_output->>'tool_use_id', ''))
                  )
              )
        ), ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY session_id, COALESCE(call_identity, 'event:' || id::text)
                ORDER BY (source_event_id IS NOT NULL AND source_event_id NOT LIKE 'native-command:%%') DESC,
                         source_timestamp DESC NULLS LAST, created_at DESC, id DESC
            ) AS result_rank
            FROM candidates
        ), attributed AS (
            SELECT r.*, COALESCE(r.tool_name, u.tool_name, 'unknown') AS resolved_tool,
                   COALESCE(u.tool_input, r.tool_input) AS call_input
            FROM ranked r
            LEFT JOIN LATERAL (
                SELECT c.tool_name, c.tool_input
                FROM session_events c
                WHERE c.session_id = r.session_id AND r.call_identity IS NOT NULL
                  AND c.event_type = 'tool_use'
                  AND COALESCE(NULLIF(c.call_id, ''), c.tool_input->>'call_id') = r.call_identity
                ORDER BY (c.source_event_id IS NOT NULL AND c.source_event_id NOT LIKE 'native-command:%%') DESC,
                         c.source_timestamp DESC NULLS LAST, c.created_at DESC, c.id DESC
                LIMIT 1
            ) u ON true
            WHERE result_rank = 1
        ), payloads AS (
            SELECT *, COALESCE(
                CASE WHEN json_typeof(tool_output->'output') = 'string' THEN tool_output->>'output' END,
                CASE WHEN json_typeof(tool_output->'content') = 'string' THEN tool_output->>'content' END,
                CASE WHEN json_typeof(tool_output->'stdout') = 'string' OR json_typeof(tool_output->'stderr') = 'string'
                     THEN COALESCE(tool_output->>'stdout', '') || COALESCE(tool_output->>'stderr', '') END,
                NULLIF((tool_output->'output')::jsonb, 'null'::jsonb)::text,
                content,
                CASE WHEN json_typeof(tool_output) = 'string' THEN tool_output #>> '{}' END,
                CASE WHEN json_typeof(tool_output) = 'array' THEN tool_output::text END,
                CASE WHEN json_typeof(tool_output) = 'object' AND
                    tool_output::jsonb - ARRAY['call_id', 'tool_use_id', 'truncated', 'output_truncated',
                        'exit_code', 'status', 'is_error', 'opaque_blocks', 'output', 'content', 'stdout', 'stderr'] <> '{}'::jsonb
                     THEN tool_output::text END
            ) AS output_text,
            CASE
                WHEN resolved_tool IN ('functions.exec', 'exec') OR call_input->'nested_exec_commands' IS NOT NULL THEN 'wrapper'
                WHEN call_input->>'wrapper_candidate_call_id' IS NOT NULL THEN 'nested'
                ELSE 'standalone'
            END AS call_kind
            FROM attributed
        ), measured AS (
            SELECT p.*, octet_length(output_text) AS output_bytes,
                CASE
                    WHEN tool_output->>'truncated' = 'true' OR tool_output->>'output_truncated' = 'true'
                      OR output_text ~* '((^|\n)Warning: truncated output \\(original token count: [0-9]+\\)|…[0-9]+ tokens truncated…)'
                        THEN true
                    WHEN tool_output->>'truncated' = 'false' OR tool_output->>'output_truncated' = 'false' THEN false
                END AS truncated,
                EXISTS (
                    SELECT 1 FROM payloads w
                    WHERE p.call_kind = 'nested' AND p.call_input->>'wrapper_correlation' = 'nested_command_digest'
                      AND w.session_id = p.session_id AND w.call_kind = 'wrapper'
                      AND w.call_identity = p.call_input->>'wrapper_candidate_call_id'
                      AND w.output_text IS NOT NULL
                ) AS nested_with_measured_wrapper
            FROM payloads p
        )
    """)


def result_hotspots_query() -> sql.Composed:
    return sql.SQL("""
        SELECT resolved_tool AS tool_name, count(*)::int AS events,
               sum(tokens)::bigint AS stored_tokens, sum(length(output_text))::bigint AS output_chars,
               COALESCE(avg(duration_ms), 0)::float AS avg_duration_ms,
               count(output_text)::int AS output_samples, count(tokens)::int AS stored_tokens_samples,
               count(*) FILTER (WHERE output_text IS NULL AND tokens IS NULL)::int AS unmeasured_events,
               call_kind, sum(output_bytes)::bigint AS output_bytes,
               percentile_disc(0.5) WITHIN GROUP (ORDER BY output_bytes) AS p50_bytes,
               percentile_disc(0.95) WITHIN GROUP (ORDER BY output_bytes) AS p95_bytes,
               max(output_bytes) AS max_bytes,
               count(*) FILTER (WHERE truncated)::int AS truncated_results,
               count(truncated)::int AS truncation_samples
        FROM ({ctes} SELECT * FROM measured) results
        GROUP BY resolved_tool, call_kind
        ORDER BY output_bytes DESC NULLS LAST, events DESC, tool_name, call_kind
        LIMIT %s;
    """).format(ctes=_result_ctes())


def result_diagnostics_query() -> sql.Composed:
    """All-result coverage and high-confidence repeats, independent of hotspot limit."""
    return sql.SQL("""
        SELECT report FROM (
            {ctes}, delivered AS (
                SELECT * FROM measured WHERE NOT nested_with_measured_wrapper
            ), retrievals AS (
                SELECT d.*, NULLIF(s.agent_slug, '') AS agent_role,
                       CASE WHEN s.external_id LIKE 'task-%%' THEN s.external_id END AS task_identity,
                       COALESCE(d.call_input->>'cmd', d.call_input->>'command', nested.command) AS command
                FROM delivered d LEFT JOIN sessions s ON s.id = d.session_id
                LEFT JOIN LATERAL (
                    SELECT CASE WHEN count(*) = 1 THEN max(COALESCE(n.call_input->>'cmd', n.call_input->>'command')) END AS command
                    FROM measured n
                    WHERE d.call_kind = 'wrapper' AND n.nested_with_measured_wrapper
                      AND n.session_id = d.session_id
                      AND n.call_input->>'wrapper_candidate_call_id' = d.call_identity
                ) nested ON true
            ), repeats AS (
                SELECT resolved_tool AS tool_name, agent_role, task_identity,
                       md5(command) AS input_digest, md5(output_text) AS output_digest,
                       count(*)::int AS retrievals, (count(*) - 1) * max(output_bytes) AS duplicate_bytes,
                       max(output_bytes) AS max_bytes,
                       CASE
                         WHEN command ~ '^st (tools (manifest|catalog)|(?:--no-compact )?context)( |$)'
                           THEN CASE WHEN command ~ '^st tools ' THEN 'st tools manifest --surface <surface> or --discover <topic>'
                                     ELSE 'st context <task> --compact; st export <task> --output <file>' END
                       END AS alternative
                FROM retrievals
                WHERE agent_role IS NOT NULL AND task_identity IS NOT NULL AND output_text IS NOT NULL
                  AND command ~ '^(st (tools (manifest|catalog)|(?:--no-compact )?context|session-events|sessions|agents|prompt|memory|search|logs)|(?:rg|grep|cat|sed|head|tail|ls|find) )'
                GROUP BY resolved_tool, agent_role, task_identity, command, md5(output_text)
                HAVING (count(*) >= 3 AND (count(*) - 1) * max(output_bytes) >= 32768)
                    OR (count(*) >= 2 AND max(output_bytes) >= 32768
                        AND command ~ '^st (tools (manifest|catalog)|(?:--no-compact )?context)( |$)')
                ORDER BY duplicate_bytes DESC, tool_name LIMIT 3
            )
            SELECT jsonb_build_object(
                'summary', (SELECT jsonb_build_object(
                    'results', count(*), 'measured_results', count(output_text), 'output_bytes', sum(output_bytes),
                    'p50_bytes', percentile_disc(0.5) WITHIN GROUP (ORDER BY output_bytes),
                    'p95_bytes', percentile_disc(0.95) WITHIN GROUP (ORDER BY output_bytes), 'max_bytes', max(output_bytes),
                    'truncated_results', count(*) FILTER (WHERE truncated), 'truncation_samples', count(truncated),
                    'named_results', count(*) FILTER (WHERE resolved_tool <> 'unknown'),
                    'call_identity_results', count(call_identity),
                    'source_timestamp_results', count(source_timestamp)
                ) FROM delivered),
                'observed_results', (SELECT count(*) FROM measured),
                'wrapper_results', (SELECT count(*) FROM measured WHERE call_kind = 'wrapper'),
                'nested_results', (SELECT count(*) FROM measured WHERE call_kind = 'nested'),
                'nested_results_excluded', (SELECT count(*) FROM measured WHERE nested_with_measured_wrapper),
                'role_task_results', (SELECT count(*) FROM retrievals WHERE agent_role IS NOT NULL AND task_identity IS NOT NULL),
                'retrieval_identity_results', (SELECT count(*) FROM retrievals WHERE command IS NOT NULL AND agent_role IS NOT NULL AND task_identity IS NOT NULL),
                'repeated_retrievals', COALESCE((SELECT jsonb_agg(to_jsonb(repeats)) FROM repeats), '[]'::jsonb)
            ) AS report
        ) diagnostics;
    """).format(ctes=_result_ctes())


def _label(value: Any, limit: int) -> str:
    label = "".join(character if character.isprintable() else " " for character in str(value))[:limit]
    # Non-BMP characters use two JSON escapes. Bound labels by escaped size as
    # well as characters so the mandatory action fits in either output mode.
    while len(json.dumps(label).encode("utf-8")) > limit * 6 + 2:
        label = label[:-1]
    return label


def cost_advisory(data: dict[str, Any]) -> dict[str, Any]:
    """Advice never treats size alone, missing telemetry, or HTTP failure as waste."""
    diagnostics = data.get("result_diagnostics", {})
    summary = diagnostics.get("summary", {})
    measured = int(summary.get("measured_results") or 0)
    truncated = int(summary.get("truncated_results") or 0)
    findings: list[str] = []
    if measured >= 20 and truncated / measured >= 0.1:
        findings.append(f"Truncation: {truncated}/{measured} retained results; narrow ranges/filters or use an existing file route.")
    for item in diagnostics.get("repeated_retrievals", [])[:3]:
        tool = _label(item.get("tool_name", "unknown"), 60)
        role = _label(item.get("agent_role", "unknown"), 40)
        task = _label(item.get("task_identity", "unknown"), 50)
        count = int(item.get("retrievals") or 0)
        duplicate = int(item.get("duplicate_bytes") or 0)
        alternative = item.get("alternative")
        if (count >= 3 and duplicate >= 32768) or (alternative and count >= 2 and int(item.get("max_bytes") or 0) >= 32768):
            route = str(alternative) if alternative else "reuse saved output; refresh when source changes"
            findings.append(f"Unchanged retrieval: {tool} x{count}, duplicate={duplicate}B, role={role}, task={task}; {route}.")
    return {
        "status": "advisory" if findings else "ok" if measured else "unknown",
        "summary": summary,
        "findings": findings,
    }


def render_cost_advisory(data: dict[str, Any]) -> str:
    """One tiny healthy/unknown line; actionable exception capped at 1,500 UTF-8 bytes."""
    advisory = cost_advisory(data)
    summary = advisory["summary"]
    measured, results = summary.get("measured_results", 0), summary.get("results", 0)
    if advisory["status"] != "advisory":
        return f"TOOLS_COST:{advisory['status'].upper()} measured={measured}/{results}; " + (
            "no retrieval advisory; capture completeness unknown." if measured else "telemetry unknown; work may continue."
        )
    diagnostics = data.get("result_diagnostics", {})
    rate = int(summary.get("truncated_results") or 0) / int(measured) * 100
    lines = [
        f"TOOLS_COST:ADVISORY measured={measured}/{results} bytes={summary.get('output_bytes', 'unknown')} "
        f"p50/p95/max={summary.get('p50_bytes')}/{summary.get('p95_bytes')}/{summary.get('max_bytes')}B",
        advisory["findings"][0],
        f"Truncated={summary.get('truncated_results', 0)}/{measured} ({rate:.1f}% lower bound); "
        f"flags={summary.get('truncation_samples', 0)}/{measured} "
        f"identity={summary.get('call_identity_results', 0)}/{results} role/task={diagnostics.get('role_task_results', 0)}/{results} "
        f"retrieval={diagnostics.get('retrieval_identity_results', 0)}/{results}",
        f"Wrapper={diagnostics.get('wrapper_results', 0)} nested={diagnostics.get('nested_results', 0)} "
        f"nested excluded={diagnostics.get('nested_results_excluded', 0)}; source time={summary.get('source_timestamp_results', 0)}/{results}",
    ]
    native = [item for item in data.get("native_usage", []) if item.get("scope") == "response"]
    if not native:
        lines.append("Model/cache usage unknown; retained bytes are not billed tokens.")
    for item in native[:2]:
        lines.append(
            f"Model={_label(item.get('model', 'unknown'), 50)} source={_label(item.get('source', 'unknown'), 50)} "
            f"cached={item.get('cached_input_tokens') if item.get('cached_input_tokens') is not None else 'unknown'} "
            f"uncached={item.get('uncached_input_tokens') if item.get('uncached_input_tokens') is not None else 'unknown'} "
            f"paired={item.get('uncached_input_tokens_samples', 0)}/{item.get('events', 0)} responses; billed cost unknown."
        )
    lines.extend(advisory["findings"][1:])
    retained: list[str] = []
    for line in lines:
        candidate = "\n".join([*retained, line])
        # Reserve room for a route to the full report. JSON escaping and human
        # indentation count too, so both CLI output modes stay within 1.5 KB.
        if len(json.dumps({"advisory": candidate}, indent=2).encode("utf-8")) > 1450:
            retained.append("More: st tools cost.")
            break
        retained.append(line)
    return "\n".join(retained)
