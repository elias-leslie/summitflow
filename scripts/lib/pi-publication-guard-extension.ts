/**
 * SummitFlow publication guard for Pi (thin: all policy lives in `publication-pretool-hook`).
 *
 * Claude Code and Codex run that hook as a PreToolUse hook; Pi has no hooks, so this extension sends the same
 * Claude-style PreToolUse payload to it on every `bash` call and every GitHub/git connector (`mcp__*`) call and
 * blocks the call with the guard's own reason when it denies. Anything but a clean allow blocks: a hook that
 * errors, times out or prints something unreadable fails closed. The hook is found next to this file (or in
 * SUMMITFLOW_SCRIPTS_DIR/lib); when it is not there, SummitFlow is not installed and the guard does not apply,
 * as for Agent Hub's own bash tool.
 */

import { spawn } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const HOOK_NAME = "publication-pretool-hook";
const HOOK_TIMEOUT_MS = 10000;
const CONNECTOR = /^mcp__.*(?:github|git).*/;

function findHook(): string | undefined {
	const here = dirname(realpathSync(fileURLToPath(import.meta.url)));
	const configured = process.env.SUMMITFLOW_SCRIPTS_DIR?.trim();
	const candidates = [configured ? join(configured, "lib", HOOK_NAME) : "", join(here, HOOK_NAME)];
	return candidates.find((path) => path && existsSync(path));
}

type Decision = { block: boolean; reason?: string };

function runHook(hook: string, payload: Record<string, unknown>): Promise<Decision> {
	return new Promise((resolve) => {
		const failed = (why: string) => resolve({ block: true, reason: `Publication guard unavailable (${why}); execution refused.` });
		const child = spawn("bash", [hook], { stdio: ["pipe", "pipe", "pipe"] });
		const out: Buffer[] = [];
		const timer = setTimeout(() => child.kill("SIGKILL"), HOOK_TIMEOUT_MS);
		child.stdout.on("data", (chunk: Buffer) => out.push(chunk));
		child.stdin.on("error", () => {});
		child.on("error", () => {
			clearTimeout(timer);
			failed("hook did not start");
		});
		child.on("close", (code, signal) => {
			clearTimeout(timer);
			if (signal || code !== 0) return failed(signal ? `hook killed by ${signal}` : `hook exited ${code}`);
			try {
				const decision = JSON.parse(Buffer.concat(out).toString("utf8")).hookSpecificOutput;
				if (decision === undefined) return resolve({ block: false });
				if (decision.permissionDecision === "deny") {
					return resolve({ block: true, reason: String(decision.permissionDecisionReason || "Blocked by the publication guard.") });
				}
				return resolve({ block: false });
			} catch {
				return failed("unreadable hook output");
			}
		});
		child.stdin.end(JSON.stringify(payload));
	});
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		const isBash = event.toolName === "bash";
		if (!isBash && !CONNECTOR.test(event.toolName)) return undefined;
		let hook: string | undefined;
		try {
			hook = findHook();
		} catch {
			hook = undefined;
		}
		if (!hook) return undefined;
		const decision = await runHook(hook, {
			hook_event_name: "PreToolUse",
			tool_name: isBash ? "Bash" : event.toolName,
			tool_input: event.input,
			tool_use_id: event.toolCallId,
			cwd: ctx.cwd,
		});
		return decision.block ? { block: true, reason: decision.reason } : undefined;
	});
}
