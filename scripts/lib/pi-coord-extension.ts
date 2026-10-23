/**
 * SummitFlow coordination adapter for Pi (thin: all logic is `st` coord code).
 *
 * Pi exports no session id to its shells, so this sets PI_SESSION_ID on every
 * session_start (startup, /new, /resume, /fork) and routes the same events the
 * Claude Code and Codex hooks use through ~/.claude/hooks/lease-check.sh:
 *   session_start          -> `session`   (reset notice, appended once to the next prompt)
 *   tool_call edit/write   -> edit mode   (auto-lease; a foreign lease WARNING is added to the tool
 *                                          result; blocks with one line only under a live acceptance/deploy)
 *   tool_call/result bash  -> bash-pre / bash-post (one warning line on a foreign-leased shell write)
 *   tool_result           -> inbox context (shared once-per-request delivery and reminders)
 *   idle/agent_end         -> surface new ST inbox requests as Pi user turns, so peers can coordinate
 * Silent when nothing overlaps; every failure allows the tool.
 */

import { spawn } from "node:child_process";

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const HOOK = `${process.env.HOME}/.claude/hooks/lease-check.sh`;
const INBOX = `${process.env.HOME}/.claude/hooks/coord-inbox.sh`;

type HookResult = { code: number; stdout: string; stderr: string };

function runHook(
	mode: string | null,
	payload: Record<string, unknown>,
	script = HOOK,
	extraArgs: string[] = [],
): Promise<HookResult> {
	return new Promise((resolve) => {
		const child = spawn("bash", mode ? [script, mode, ...extraArgs] : [script], { stdio: ["pipe", "pipe", "pipe"] });
		const out: Buffer[] = [];
		const err: Buffer[] = [];
		const timer = setTimeout(() => child.kill("SIGKILL"), 5000);
		child.stdout.on("data", (chunk: Buffer) => out.push(chunk));
		child.stderr.on("data", (chunk: Buffer) => err.push(chunk));
		child.stdin.on("error", () => {}); // A missing/early-exiting hook must fail open, including EPIPE.
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

function additionalContext(result: HookResult): string | undefined {
	try {
		return result.stdout ? JSON.parse(result.stdout).hookSpecificOutput?.additionalContext : undefined;
	} catch {
		return undefined;
	}
}

export default function (pi: ExtensionAPI) {
	let notice: string | undefined;
	let inboxTimer: NodeJS.Timeout | undefined;
	let inboxBusy = false;
	let sessionGeneration = 0;
	const editWarnings = new Map<string, string>();

	const base = (ctx: ExtensionContext) => ({
		session_id: ctx.sessionManager.getSessionId(),
		cwd: ctx.sessionManager.getCwd(),
	});
	const checkInbox = async (ctx: ExtensionContext, generation: number) => {
		if (inboxBusy || !ctx.isIdle() || generation !== sessionGeneration) return;
		inboxBusy = true;
		try {
			const result = await runHook("turn", {
				...base(ctx),
				hook_event_name: "PiIdle",
			}, INBOX, ["pi"]);
			const message = additionalContext(result);
			if (message && generation === sessionGeneration) {
				pi.sendUserMessage(message, { deliverAs: "followUp" });
			}
		} catch {
			// A coordination check must never interrupt the current Pi turn.
		} finally {
			inboxBusy = false;
		}
	};

	pi.on("session_start", async (event, ctx) => {
		if (inboxTimer) clearInterval(inboxTimer);
		sessionGeneration += 1;
		process.env.PI_SESSION_ID = ctx.sessionManager.getSessionId();
		const result = await runHook("session", {
			...base(ctx),
			hook_event_name: "SessionStart",
			source: event.reason === "new" ? "clear" : event.reason,
		});
		notice = additionalContext(result);
		const generation = sessionGeneration;
		inboxTimer = setInterval(() => { void checkInbox(ctx, generation); }, 15_000);
		inboxTimer.unref();
		void checkInbox(ctx, generation);
	});

	pi.on("agent_end", async (_event, ctx) => {
		await checkInbox(ctx, sessionGeneration);
	});

	pi.on("session_shutdown", () => {
		if (inboxTimer) clearInterval(inboxTimer);
		inboxTimer = undefined;
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
			const warning = additionalContext(result);
			if (warning) editWarnings.set(event.toolCallId, warning);
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
		const context: string[] = [];
		const warning = editWarnings.get(event.toolCallId);
		if (warning !== undefined) {
			editWarnings.delete(event.toolCallId);
			context.push(warning);
		}
		if (event.toolName === "bash") {
			const result = await runHook("bash-post", {
				...base(ctx),
				hook_event_name: "PostToolUse",
				tool_name: "Bash",
				tool_use_id: event.toolCallId,
			});
			if (result.code === 2 && result.stderr) context.push(result.stderr);
		}
		const inbox = await runHook("turn", {
			...base(ctx),
			hook_event_name: "PostToolUse",
		}, INBOX, ["pi"]);
		const message = additionalContext(inbox);
		if (message) context.push(message);
		if (context.length) {
			return { content: [...event.content, ...context.map((text) => ({ type: "text" as const, text }))] };
		}
	});
}
