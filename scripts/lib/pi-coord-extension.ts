/**
 * SummitFlow coordination adapter for Pi (thin: all logic is `st` coord code).
 *
 * Pi exports no session id to its shells, so this sets PI_SESSION_ID on every
 * session_start (startup, /new, /resume, /fork) and routes the same events the
 * Claude Code and Codex hooks use through ~/.claude/hooks/lease-check.sh:
 *   session_start          -> `session`   (reset notice, appended once to the next prompt)
 *   tool_call edit/write   -> edit mode   (auto-lease; blocks with one line on a live collision)
 *   tool_call/result bash  -> bash-pre / bash-post (one warning line on a foreign-leased shell write)
 * Silent when nothing overlaps; every failure allows the tool.
 */

import { spawn } from "node:child_process";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const HOOK = `${process.env.HOME}/.claude/hooks/lease-check.sh`;

type HookResult = { code: number; stdout: string; stderr: string };

function runHook(mode: string | null, payload: Record<string, unknown>): Promise<HookResult> {
	return new Promise((resolve) => {
		const child = spawn("bash", mode ? [HOOK, mode] : [HOOK], { stdio: ["pipe", "pipe", "pipe"] });
		const out: Buffer[] = [];
		const err: Buffer[] = [];
		const timer = setTimeout(() => child.kill("SIGKILL"), 5000);
		child.stdout.on("data", (chunk: Buffer) => out.push(chunk));
		child.stderr.on("data", (chunk: Buffer) => err.push(chunk));
		child.on("error", () => {
			clearTimeout(timer);
			resolve({ code: 0, stdout: "", stderr: "" });
		});
		child.on("close", (code) => {
			clearTimeout(timer);
			resolve({
				code: code ?? 0,
				stdout: Buffer.concat(out).toString("utf8").trim(),
				stderr: Buffer.concat(err).toString("utf8").trim(),
			});
		});
		child.stdin.end(JSON.stringify(payload));
	});
}

export default function (pi: ExtensionAPI) {
	let notice: string | undefined;

	const base = (ctx: ExtensionContext) => ({
		session_id: ctx.sessionManager.getSessionId(),
		cwd: ctx.sessionManager.getCwd(),
	});

	pi.on("session_start", async (event, ctx) => {
		process.env.PI_SESSION_ID = ctx.sessionManager.getSessionId();
		const result = await runHook("session", {
			...base(ctx),
			hook_event_name: "SessionStart",
			source: event.reason === "new" ? "clear" : event.reason,
		});
		try {
			notice = result.stdout ? JSON.parse(result.stdout).hookSpecificOutput?.additionalContext : undefined;
		} catch {
			notice = undefined;
		}
	});

	pi.on("before_agent_start", async (event) => {
		if (!notice) return;
		const line = notice;
		notice = undefined;
		return { systemPrompt: `${event.systemPrompt}\n\n${line}` };
	});

	pi.on("tool_call", async (event, ctx) => {
		const input = (event.input ?? {}) as Record<string, unknown>;
		if (event.toolName === "edit" || event.toolName === "write") {
			const result = await runHook(null, {
				...base(ctx),
				hook_event_name: "PreToolUse",
				tool_name: "Edit",
				tool_input: { file_path: input.path },
			});
			if (result.code === 2 && result.stderr) return { block: true, reason: result.stderr };
		} else if (event.toolName === "bash") {
			await runHook("bash-pre", {
				...base(ctx),
				hook_event_name: "PreToolUse",
				tool_name: "Bash",
				tool_use_id: event.toolCallId,
			});
		}
	});

	pi.on("tool_result", async (event, ctx) => {
		if (event.toolName !== "bash") return;
		const result = await runHook("bash-post", {
			...base(ctx),
			hook_event_name: "PostToolUse",
			tool_name: "Bash",
			tool_use_id: event.toolCallId,
		});
		if (result.code === 2 && result.stderr) {
			return { content: [...event.content, { type: "text", text: result.stderr }] };
		}
	});
}
