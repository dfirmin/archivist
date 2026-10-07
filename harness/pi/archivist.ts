/**
 * Archivist's Pi extension: the three Claude Code tools the engine's prompts name and Pi lacks.
 *
 *   Agent     — spawn an engine agent as a separate headless `pi` process (its own context, as a
 *               Claude Code sub-agent has) and return its final message. Same parameters as
 *               Claude Code's tool, so `conductor.md` and the run plan read the same on both
 *               harnesses. Several `Agent` calls in one message run in parallel: Pi executes a
 *               message's tool calls concurrently.
 *   Skill     — return an engine skill's SKILL.md (the enricher and extractor load method skills).
 *   TodoWrite — accept the conductor's checklist; it is the conductor's own bookkeeping.
 *
 * Everything an agent needs is resolved by Python at install time (ADR 0008): the agent's
 * model, its Pi tool list and a prompt file with its preloaded skills appended, in
 * `<agent dir>/agents/<name>.json`. This file only reads that and spawns; it decides nothing.
 *
 * Environment (set by archivist.pi_harness):
 *   PI_CODING_AGENT_DIR        the run's private agent dir
 *   ARCHIVIST_PI_ROSTER        comma list of agents `Agent` may spawn (the run plan's roster)
 *   ARCHIVIST_PI_PROVIDER      provider for every spawn (anthropic | archivist-gateway)
 *   ARCHIVIST_PI_EVENTS_DIR    where each sub-agent's JSONL events are written, one file per call
 */

import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const RESULT_CAP = 100 * 1024;
const BRIEF_KEYS = ["command", "path", "file_path", "pattern", "skill", "subagent_type", "description"];

interface AgentSpec {
	name: string;
	model: string;
	tools: string[];
	prompt_file: string;
}

interface Usage {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
	turns: number;
}

function agentDir(): string {
	const dir = process.env.PI_CODING_AGENT_DIR;
	if (!dir) throw new Error("PI_CODING_AGENT_DIR is not set; archivist starts pi with it");
	return dir;
}

function roster(): string[] {
	return (process.env.ARCHIVIST_PI_ROSTER ?? "")
		.split(",")
		.map((s) => s.trim())
		.filter(Boolean);
}

function loadSpec(name: string): AgentSpec {
	const file = path.join(agentDir(), "agents", `${name}.json`);
	if (!fs.existsSync(file)) throw new Error(`no agent definition for '${name}' (${file})`);
	return JSON.parse(fs.readFileSync(file, "utf-8")) as AgentSpec;
}

function brief(args: Record<string, unknown> | undefined): string {
	if (!args) return "";
	for (const key of BRIEF_KEYS) {
		const value = args[key];
		if (typeof value === "string" && value.trim()) {
			const text = value.split(/\s+/).join(" ");
			return text.length <= 100 ? text : `${text.slice(0, 99)}…`;
		}
	}
	return "";
}

function say(line: string): void {
	process.stderr.write(`${line}\n`);
}

/** The pi command to re-run: the same script under the same runtime when we can find it. */
function piInvocation(args: string[]): { command: string; args: string[] } {
	const script = process.argv[1];
	if (script && fs.existsSync(script)) return { command: process.execPath, args: [script, ...args] };
	return { command: "pi", args };
}

function textOf(message: any): string {
	if (!message || !Array.isArray(message.content)) return "";
	return message.content
		.filter((part: any) => part?.type === "text" && typeof part.text === "string")
		.map((part: any) => part.text)
		.join("\n")
		.trim();
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "Agent",
		label: "Agent",
		description:
			"Launch an engine sub-agent to handle one task. It starts with no memory of this " +
			"conversation: the prompt is everything it gets. Returns the sub-agent's final message. " +
			"Several Agent calls in one message run in parallel.",
		parameters: Type.Object({
			subagent_type: Type.String({ description: "The engine agent to run (one of this run's roster)" }),
			description: Type.String({ description: "A short label for this task" }),
			prompt: Type.String({ description: "The complete task for the sub-agent" }),
		}),
		async execute(toolCallId, params, signal, onUpdate, ctx) {
			const name = String(params.subagent_type ?? "").trim();
			const allowed = roster();
			if (!allowed.includes(name)) {
				throw new Error(
					`Agent type '${name}' is not in this run's roster. Available: ${allowed.join(", ") || "none"}`,
				);
			}
			const spec = loadSpec(name);
			const provider = process.env.ARCHIVIST_PI_PROVIDER || "anthropic";
			const args = [
				"--mode", "json", "-p", "--no-session", "-nc",
				"--provider", provider,
				"--model", spec.model,
				"--tools", spec.tools.join(","),
				"--append-system-prompt", spec.prompt_file,
			];
			const label = `  [${name}] `;
			const eventsDir = process.env.ARCHIVIST_PI_EVENTS_DIR;
			let sink: fs.WriteStream | undefined;
			if (eventsDir) {
				fs.mkdirSync(eventsDir, { recursive: true });
				sink = fs.createWriteStream(path.join(eventsDir, `${toolCallId}.jsonl`), { flags: "w" });
			}

			const usage: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0, turns: 0 };
			let finalText = "";
			let stopReason: string | undefined;
			let errorMessage: string | undefined;
			let stderr = "";
			const started = Date.now();

			const exitCode = await new Promise<number>((resolve) => {
				const { command, args: argv } = piInvocation(args);
				const proc = spawn(command, argv, {
					cwd: ctx.cwd,
					env: process.env,
					shell: false,
					stdio: ["pipe", "pipe", "pipe"],
				});
				proc.stdin.end(String(params.prompt ?? ""));
				let buffer = "";

				const onLine = (line: string) => {
					if (!line.trim()) return;
					sink?.write(`${line}\n`);
					let event: any;
					try {
						event = JSON.parse(line);
					} catch {
						return;
					}
					if (event.type === "tool_execution_start") {
						const b = brief(event.args);
						say(`${label}[tool] ${event.toolName}${b ? `(${b})` : ""}`);
						onUpdate?.({ content: [{ type: "text", text: `(${name} running: ${event.toolName})` }], details: {} });
					} else if (event.type === "tool_execution_end" && event.isError) {
						say(`${label}[tool-error] ${textOf(event.result).split(/\s+/).join(" ").slice(0, 160)}`);
					} else if (event.type === "message_end" && event.message?.role === "assistant") {
						const msg = event.message;
						usage.turns++;
						const u = msg.usage ?? {};
						usage.input += u.input || 0;
						usage.output += u.output || 0;
						usage.cacheRead += u.cacheRead || 0;
						usage.cacheWrite += u.cacheWrite || 0;
						usage.cost += u.cost?.total || 0;
						if (msg.stopReason) stopReason = msg.stopReason;
						if (msg.errorMessage) errorMessage = msg.errorMessage;
						const text = textOf(msg);
						if (text) {
							finalText = text;
							say(`${label}${text}`);
						}
						onUpdate?.({ content: [{ type: "text", text: `(${name} turn ${usage.turns})` }], details: {} });
					}
				};

				proc.stdout.on("data", (chunk) => {
					buffer += chunk.toString();
					const lines = buffer.split("\n");
					buffer = lines.pop() ?? "";
					for (const line of lines) onLine(line);
				});
				proc.stderr.on("data", (chunk) => {
					stderr += chunk.toString();
				});
				proc.on("close", (code) => {
					if (buffer.trim()) onLine(buffer);
					resolve(code ?? 0);
				});
				proc.on("error", (err) => {
					stderr += String(err);
					resolve(1);
				});
				if (signal) {
					const kill = () => {
						proc.kill("SIGTERM");
						setTimeout(() => proc.killed || proc.kill("SIGKILL"), 5000);
					};
					if (signal.aborted) kill();
					else signal.addEventListener("abort", kill, { once: true });
				}
			});
			sink?.end();

			const failed = exitCode !== 0 || stopReason === "error" || stopReason === "aborted";
			const details = {
				agent: name,
				model: spec.model,
				usage,
				stopReason,
				exitCode,
				durationMs: Date.now() - started,
			};
			if (failed) {
				const reason = errorMessage || stderr.trim().slice(-2000) || finalText || `exit ${exitCode}`;
				return { content: [{ type: "text", text: `Sub-agent ${name} failed: ${reason}` }], details, isError: true };
			}
			const text = finalText.length > RESULT_CAP ? `${finalText.slice(0, RESULT_CAP)}\n[truncated]` : finalText;
			return { content: [{ type: "text", text: text || "(no output)" }], details };
		},
	});

	pi.registerTool({
		name: "Skill",
		label: "Skill",
		description:
			"Load an engine skill by name and return its instructions. Use when a prompt tells you " +
			"to load a skill, or a listed skill matches the task.",
		parameters: Type.Object({
			skill: Type.String({ description: "The skill name, e.g. implementation-logic" }),
			args: Type.Optional(Type.String({ description: "Ignored; accepted for compatibility" })),
		}),
		async execute(_id, params) {
			const name = String(params.skill ?? "").trim().replace(/^\//, "");
			const dir = path.join(agentDir(), "skills", name);
			const file = path.join(dir, "SKILL.md");
			if (!/^[a-z0-9-]+$/.test(name) || !fs.existsSync(file)) {
				const known = fs.existsSync(path.join(agentDir(), "skills"))
					? fs.readdirSync(path.join(agentDir(), "skills")).join(", ")
					: "none";
				throw new Error(`Unknown skill '${name}'. Available: ${known}`);
			}
			const body = fs.readFileSync(file, "utf-8");
			return { content: [{ type: "text", text: `Base directory for this skill: ${dir}\n\n${body}` }], details: {} };
		},
	});

	pi.registerTool({
		name: "TodoWrite",
		label: "TodoWrite",
		description: "Record your task checklist (the full list each time).",
		parameters: Type.Object({
			todos: Type.Array(
				Type.Object({
					content: Type.String(),
					status: Type.String({ description: "pending | in_progress | completed" }),
				}, { additionalProperties: true }),
			),
		}),
		async execute(_id, params) {
			const lines = (params.todos ?? []).map((t: any) => `- [${t.status}] ${t.content}`);
			return { content: [{ type: "text", text: `Todos updated:\n${lines.join("\n")}` }], details: {} };
		},
	});
}
