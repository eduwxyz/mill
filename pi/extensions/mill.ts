/**
 * mill — the front of the factory inside pi, in live columns.
 *
 * One command: `/research <idea>`. It triggers the divergent-research ADW and
 * shows BOTH minds working side by side, with the tools each one uses, while
 * they use them. Then the architect, at full width.
 *
 * ── Why this extension is a VIEWER, not an orchestrator ──
 *
 * The fusion harness that inspired this one commands: the extension spawns the
 * agents, drives the loop, and renders. That is 2,500 lines, and it makes sense
 * there — pi is its home.
 *
 * Here the home is Python: it owns sequencing, gates, the trace, and SQLite,
 * and none of that should change language to gain a layout. Except that the
 * factory ALREADY writes each agent's raw JSONL to
 *
 *     adws/adw_data/sessions/<adw_id>/<agent>/raw_output.jsonl
 *
 * which is exactly the stream the columns need. So the extension spawns no
 * agent at all: it triggers the ADW, discovers the `adw_id` on the first line
 * of output, and FOLLOWS THOSE FILES.
 *
 * The gain is not only size. It is that the source of truth stays the disk: if
 * the extension dies, hangs, or you close pi, the ADW keeps running and the
 * trace stays intact. The screen is disposable on purpose — that is how Mill
 * stopped losing work to UI.
 */

import { spawn, type ChildProcess } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import {
  type ExtensionAPI,
  createBashToolDefinition, createEditToolDefinition, createFindToolDefinition,
  createGrepToolDefinition, createLsToolDefinition, createReadToolDefinition,
  createWriteToolDefinition,
} from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { Container, Text, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

const CUSTOM_TYPE = "mill";

/**
 * The last net: NOTHING leaves here wider than the terminal.
 *
 * A line one character too wide brings down the whole pi session ("Rendered
 * line exceeds terminal width"), and the engineer loses the conversation over a
 * drawing. It happened once, in the middle of a research run.
 *
 * Every place that composes a line already truncates. This exists because
 * "every place" is a promise that breaks on the next edit, and the cost of
 * failing here is out of proportion to the mistake. One character of slack
 * guards against rounding on wide characters (CJK, emoji), which count as 2 and
 * are sometimes measured as 1.
 */
function safeLines(lines: string[], width: number): string[] {
  const limit = Math.max(1, width - 1);
  return lines.map((l) => (visibleWidth(l) > limit ? truncateToWidth(l, limit) : l));
}

/**
 * PI'S OWN renderers, reused.
 *
 * Drawing the lines by hand (`▸ read path`) looked wrong in a specific way: it
 * looked like a different tool. The agent running inside the panel is a `pi`,
 * and the engineer already knows how to read pi output — reproducing it halfway
 * asks them to learn a second dialect to see the same thing.
 *
 * Every pi built-in tool exposes `renderCall(args, theme, ctx)`, which is
 * exactly what its TUI calls. Passing the same arguments, the panel shows what
 * pi would show.
 */
const RENDERERS: Record<string, (cwd: string) => any> = {
  read: createReadToolDefinition,
  bash: createBashToolDefinition,
  edit: createEditToolDefinition,
  write: createWriteToolDefinition,
  grep: createGrepToolDefinition,
  find: createFindToolDefinition,
  ls: createLsToolDefinition,
};
const rendererCache = new Map<string, any>();

function renderLikePi(tool: string, args: any, cwd: string, theme: any, width: number): string[] | null {
  const make = RENDERERS[tool];
  if (!make) return null;
  try {
    const key = `${tool}:${cwd}`;
    if (!rendererCache.has(key)) rendererCache.set(key, make(cwd));
    const def = rendererCache.get(key);
    if (!def?.renderCall) return null;
    // The context the TUI passes. `invalidate` is a no-op because there is no
    // per-event redraw here: the whole widget is repainted every tick.
    const component = def.renderCall(args, theme, {
      args, toolCallId: "", invalidate: () => {}, lastComponent: undefined,
      state: {}, cwd, executionStarted: true,
    });
    return component?.render?.(width) ?? null;
  } catch {
    return null;
  }
}

const TICK_MS = 700;
const MIN_TWO_COL = 100;
const MAX_LINES = 14;
const fmt = (s: number) => s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
const SESSIONS = "adws/adw_data/sessions";

/**
 * Every command declares WHO it watches, and who closes.
 *
 * `cols` run together and become columns; `closer` comes afterwards and takes
 * the full width. A single-agent command has a `cols` of length 1 — and then
 * "two columns" degenerates into one, with no special case at all.
 */
interface Shape {
  argv: string[];
  cols: string[];
  closer?: string;
  label: string;

  /** Joins the previous session — this is what stitches a feature into one trace. */
  joins?: boolean;
}

interface Flow {
  agent: string;
  lines: string[];
  tools: number;
  done: boolean;

  /**
   * File → byte already read. Several of them, because a column can be a
   * TICKET, and a ticket has a gatekeeper, a builder and a reviewer — three
   * streams in one column, interleaved in the order things happened, which is
   * the order that matters.
   *
   * The offset avoids re-reading the whole file every tick, which would be
   * O(n²).
   */
  offset: Map<string, number>;

  /**
   * Per-call arguments, kept from the ANNOUNCEMENT.
   *
   * Pi announces the call (`tool_execution_start`, or a `toolCall` block inside
   * `message_end`) with the arguments, and later emits `tool_execution_end`
   * with `args` EMPTY. Reading only the end gave `▸ read` without saying what —
   * the tool name without the target, which is precisely the useless half. It
   * is the same fold Python's `ToolCallTracker` does.
   */
  pending: Map<string, Record<string, any>>;

  /** The completed calls, in order — the render draws them with pi. */
  calls: { tool: string; args: any; failed: boolean }[];
}

const flow = (agent: string): Flow =>
  ({ agent, lines: [], tools: 0, done: false, offset: new Map(), pending: new Map(), calls: [] });

// ── reading the raw JSONL ───────────────────────────────────────────────────

/**
 * One readable line per event — the same pair of events that Python's
 * `ToolCallTracker` folds into a single record.
 *
 * Only `tool_execution_end` becomes a line: the `_start` arrives without a
 * result, and showing both would make every tool appear twice in the column.
 */
function toLine(event: any, f: Flow): string | null {
  const type = event?.type;

  // ── announcements: hold the arguments until the call finishes ──
  if (type === "tool_execution_start" && event.toolCallId) {
    f.pending.set(String(event.toolCallId), event.args ?? {});
  }
  if (type === "message_end") {
    for (const block of event.message?.content ?? []) {
      if (block?.type === "toolCall" && block.id) {
        f.pending.set(String(block.id), block.arguments ?? {});
      }
    }
  }

  if (type === "tool_execution_end") {
    const tool = event.toolName ?? "tool";
    const id = String(event.toolCallId ?? "");
    const args = { ...(f.pending.get(id) ?? {}), ...(event.args ?? {}) };
    f.pending.delete(id);
    f.calls.push({ tool, args, failed: Boolean(event.isError) });
    if (f.calls.length > MAX_LINES * 3) f.calls.splice(0, f.calls.length - MAX_LINES * 3);
    return null;
  }
  if (type === "message_end" && event.message?.role === "assistant") {
    const text = (event.message.content ?? [])
      .filter((b: any) => b?.type === "text")
      .map((b: any) => b.text)
      .join("")
      .trim();
    // The final answer is long and goes to the file anyway; in the column, only
    // the first sentence, to show a sign of life without becoming a wall.
    return text ? `  ${text.split("\n")[0]}` : null;
  }
  return null;
}

/** Reads only what arrived since last time, in each of the flow's files. */
function drain(file: string, f: Flow): void {
  const readOffset = f.offset.get(file) ?? 0;
  let size: number;
  try {
    size = fs.statSync(file).size;
  } catch {
    return;
  }
  if (size <= readOffset) return;
  let chunk = "";
  try {
    const fd = fs.openSync(file, "r");
    const buf = Buffer.alloc(size - readOffset);
    fs.readSync(fd, buf, 0, buf.length, readOffset);
    fs.closeSync(fd);
    chunk = buf.toString("utf8");
  } catch {
    return;
  }
  // A partial line at the end is normal — the agent is still writing it.
  const lines = chunk.split("\n");
  const trailing = lines.pop() ?? "";
  f.offset.set(file, size - Buffer.byteLength(trailing, "utf8"));

  for (const raw of lines) {
    if (!raw.trim()) continue;
    let event: any;
    try { event = JSON.parse(raw); } catch { continue; }
    const line = toLine(event, f);
    if (!line) continue;
    if (line.startsWith("▸")) f.tools++;
    f.lines.push(line);
    if (f.lines.length > MAX_LINES * 3) f.lines.splice(0, f.lines.length - MAX_LINES * 3);
  }
}

// ── layout ──────────────────────────────────────────────────────────────────

function box(f: Flow, width: number, theme: any, cwd: string): string[] {
  const head = theme.bold(f.agent) +
    theme.fg("dim", `  ${f.tools} tools${f.done ? " · done" : ""}`);

  // The last calls, drawn by pi. Each one can take more than one line (`bash`
  // shows the command; `edit`, the diff), so the cut happens at the end, over
  // the LINES — cutting by call would leave the last one halved or waste the
  // height.
  const body: string[] = [];
  for (const call of f.calls) {
    const drawn = renderLikePi(call.tool, call.args, cwd, theme, width);
    const lines = drawn ?? [theme.fg("dim", `${call.tool} ${JSON.stringify(call.args).slice(0, width - 8)}`)];
    // ALWAYS TRUNCATE, including what came from pi's own renderer.
    //
    // A line one character wider than the terminal does not misalign: it BRINGS
    // DOWN the whole session ("Rendered line exceeds terminal width"), and the
    // engineer loses the conversation over a drawing. Pi's renderer pads to the
    // width you asked for, but OSC-8 hyperlinks and color make the visible
    // length diverge from the raw one — trusting it here cost a work session.
    for (const l of lines) {
      const clipped = truncateToWidth(l, width);
      body.push(call.failed ? theme.fg("error", clipped) : clipped);
    }
  }
  for (const l of f.lines) body.push(theme.fg("dim", truncateToWidth(l, width)));

  const shown = body.slice(-MAX_LINES);
  const filler = Array.from({ length: Math.max(0, MAX_LINES - shown.length) }, () => "");
  return [truncateToWidth(head, width), ...shown, ...filler];
}

/** Two columns when it fits; stacked when it does not. */
function twoCol(left: string[], right: string[], width: number): string[] {
  if (width < MIN_TWO_COL) return [...left, "", ...right];
  const gutter = "   ";
  const colW = Math.floor((width - visibleWidth(gutter)) / 2);
  const rows = Math.max(left.length, right.length);
  // Cut BEFORE padding, and on both sides: padding a line that already passed
  // the column only pushes the overflow further along.
  const cell = (s: string) => {
    const clipped = truncateToWidth(s, colW);
    return clipped + " ".repeat(Math.max(0, colW - visibleWidth(clipped)));
  };
  const out: string[] = [];
  for (let i = 0; i < rows; i++) out.push(cell(left[i] ?? "") + gutter + truncateToWidth(right[i] ?? "", colW));
  return out;
}

// ── the extension ───────────────────────────────────────────────────────────

export default function (pi: ExtensionAPI) {
  let child: ChildProcess | undefined;

  /**
   * The last `adw_id`, remembered between commands.
   *
   * Without this the engineer would have to copy an eight-digit hash from one
   * command to the next, every time, and one typo would split what was a single
   * feature into two traces. The extension knows which one was last — which is,
   * in every real conversation, the one they want to continue.
   */
  let lastAdwId = "";

  /** Triggers an ADW, follows the agents' files, and returns the outcome. */
  const runAdw = async (ctx: any, shape: Shape): Promise<{ ok: boolean; adwId: string; tail: string }> => {
    const adws = path.join(ctx.cwd, "adws");
    if (!fs.existsSync(adws)) {
      ctx.ui.notify(
        "mill: this repository does not have Mill installed — run  " +
        "uv run ~/.claude/skills/mill/scripts/install.py", "error");
      return { ok: false, adwId: "", tail: "" };
    }

    const watched = [...shape.cols, ...(shape.closer ? [shape.closer] : [])];
    const flows = new Map<string, Flow>(watched.map((a) => [a, flow(a)]));
    const argv = [...shape.argv];
    if (shape.joins && lastAdwId) argv.push("--adw-id", lastAdwId);

    let adwId = shape.joins ? lastAdwId : "";
    let out = "";
    let failure = "";
    const startedAt = Date.now();

    child = spawn("uv", ["run", ...argv], { cwd: ctx.cwd, stdio: ["ignore", "pipe", "pipe"] });
    child.stdout?.on("data", (b: Buffer) => {
      const text = b.toString();
      out += text;
      const found = text.match(/adw_id:\s*([0-9a-f]+)/);
      if (found && !adwId) adwId = found[1]!;
    });
    child.stderr?.on("data", (b: Buffer) => { failure += b.toString(); });

    const timer = setInterval(() => {
      if (adwId) for (const [agent, f] of flows) {
        drain(path.join(ctx.cwd, SESSIONS, adwId, agent, "raw_output.jsonl"), f);
      }
      const elapsed = Math.round((Date.now() - startedAt) / 1000);
      ctx.ui.setWidget(CUSTOM_TYPE, (_tui: any, theme: any) => {
        const c = new Container();
        c.addChild(new Text(
          theme.fg("customMessageLabel", theme.bold(`MILL · ${shape.label}`)) +
          theme.fg("dim", `  ${elapsed}s${adwId ? ` · ${adwId}` : " · starting"}`), 1, 0));
        c.addChild(new Text("", 0, 0));
        c.addChild({
          render: (width: number) => safeLines(((): string[] => {
            // Half of one column: `floor(width/2)` on its own does not discount
            // the gutter, and two full halves plus the separator exceed the
            // width.
            const half = Math.floor((width - 3) / 2);
            const boxes = shape.cols.map((a) =>
              box(flows.get(a)!, shape.cols.length > 1 ? half : width, theme, ctx.cwd));
            const rows = boxes.length > 1 ? twoCol(boxes[0]!, boxes[1]!, width) : boxes[0]!;
            const end = shape.closer ? flows.get(shape.closer)! : undefined;
            // The closer only appears once it starts: an empty box is noise, and
            // the space belongs to whoever is working right now.
            if (end && (end.calls.length || end.lines.length)) rows.push("", ...box(end, width, theme, ctx.cwd));
            return rows;
          })(), width),
        } as any);
        return c;
      });
    }, TICK_MS);

    await new Promise<void>((resolve) => {
      child!.on("exit", (code) => {
        if (code !== 0) failure ||= `exited with code ${code}`;
        resolve();
      });
      child!.on("error", (e) => { failure = String(e); resolve(); });
    });

    clearInterval(timer);
    if (adwId) for (const [agent, f] of flows) {
      drain(path.join(ctx.cwd, SESSIONS, adwId, agent, "raw_output.jsonl"), f);
      f.done = true;
    }
    ctx.ui.setWidget(CUSTOM_TYPE, undefined);
    child = undefined;
    if (adwId) lastAdwId = adwId;

    // The last useful lines of the ADW's output: it already prints a good
    // summary, and rewriting it here would be two versions of the truth to keep
    // in sync.
    const tail = out.split("\n").filter((l) => l.trim()).slice(-18).join("\n");
    if (failure) ctx.ui.notify(`mill: ${shape.label} failed — ${failure.trim().slice(0, 300)}`, "error");
    return { ok: !failure, adwId, tail };
  };

  const ok = (ctx: any, adwId: string, tail: string, extra = "") =>
    pi.sendMessage({
      customType: CUSTOM_TYPE,
      content: `**Completed** · \`${adwId}\`\n\n${extra}${extra ? "\n\n" : ""}\`\`\`\n${tail}\n\`\`\``,
      display: true,
    });

  const read = (ctx: any, ...parts: string[]) => {
    const file = path.join(ctx.cwd, ...parts);
    return fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
  };

  // ── 1. divergent research: the idea is still vague ──
  pi.registerCommand("research", {
    description: "Divergent research: two isolated minds study the SAME idea and an architect decides. Use when the idea is vague.",
    handler: async (args, ctx) => {
      if (!args.trim()) return ctx.ui.notify("mill: /research <idea>", "error");
      const r = await runAdw(ctx, {
        argv: ["adws/adw_research_fusion.py", args.trim()],
        cols: ["researcher_a", "researcher_b"], closer: "architect",
        label: "divergent research",
      });
      if (!r.ok) return;
      const design = read(ctx, SESSIONS, r.adwId, "context_handoff", "design.md");
      ok(ctx, r.adwId, r.tail, design || "⚠ `design.md` is not on disk—the architect reported success without delivering it.");
    },
  });

  // ── 2. investigate: ONE question from the interview, not an idea ──
  pi.registerCommand("investigate", {
    description: "Answers ONE question with evidence: two minds, about one minute, pennies. Use it during an interview rather than returning the question to the engineer.",
    handler: async (args, ctx) => {
      if (!args.trim()) return ctx.ui.notify("mill: /investigate <a question>", "error");
      const r = await runAdw(ctx, {
        argv: ["adws/adw_research_fusion.py", args.trim(), "--question"],
        cols: ["researcher_a", "researcher_b"], closer: "architect",
        label: "investigating",
      });
      if (!r.ok) return;
      ok(ctx, r.adwId, r.tail, read(ctx, SESSIONS, r.adwId, "context_handoff", "design.md"));
    },
  });

  // ── 3. spec ──
  pi.registerCommand("spec", {
    description: "Synthesizes the decided design into a seven-section spec. Pass YOUR answers to the architect's questions. --title <feature-name> names the directory.",
    handler: async (args, ctx) => {
      if (!args.trim()) return ctx.ui.notify('mill: /spec "<your answers>" [--title <feature>]', "error");
      if (!lastAdwId) ctx.ui.notify("mill: no prior research in this session—the spec will open a new trace", "warn");
      const r = await runAdw(ctx, {
        argv: ["adws/adw_spec.py", ...splitArgs(args)],
        cols: ["speccer"], label: "spec", joins: true,
      });
      if (r.ok) ok(ctx, r.adwId, r.tail, "👤 **Read the spec before splitting it into tickets**—a wrong spec creates N wrong tickets.");
    },
  });

  // ── 4. tickets ──
  pi.registerCommand("tickets", {
    description: "Splits the spec into vertical slices with a blocking graph. Pass the spec path.",
    handler: async (args, ctx) => {
      if (!args.trim()) return ctx.ui.notify("mill: /tickets .scratch/<feature>/spec.md", "error");
      const r = await runAdw(ctx, {
        argv: ["adws/adw_tickets.py", ...splitArgs(args)],
        cols: ["slicer"], label: "tickets", joins: true,
      });
      if (r.ok) ok(ctx, r.adwId, r.tail, "👤 **Approve the split**—a wrong split creates N wrong runs. Then use `/frontier`.");
    },
  });

  // ── 5. one ticket ──
  pi.registerCommand("run", {
    description: "Builds ONE ticket: an acceptance criterion that must fail first, then build, verify, review, and commit.",
    handler: async (args, ctx) => {
      if (!args.trim()) return ctx.ui.notify("mill: /run .scratch/<feature>/issues/01-....md", "error");
      const r = await runAdw(ctx, {
        argv: ["adws/adw_run.py", ...resolveTicket(ctx.cwd, splitArgs(args))],
        cols: ["gatekeeper", "builder"], closer: "reviewer", label: "run",
      });
      if (r.ok) ok(ctx, r.adwId, r.tail);
    },
  });

  // ── 6. the frontier: genuinely AFK ──
  //
  // No columns, and on purpose: each ticket opens its OWN adw_id, so there is
  // no pair of files to follow — there is a sequence of them. What matters here
  // is which ticket is running and what is already complete, and the loop
  // already prints that. Columns would be decoration over the wrong
  // information.
  pi.registerCommand("frontier", {
    description: "AFK: works through the ticket frontier until it is empty or one fails. Pass the issues/ directory. Use --dry to see the order without spending.",
    handler: async (args, ctx) => {
      if (!args.trim()) return ctx.ui.notify("mill: /frontier .scratch/<feature>/issues [--dry]", "error");
      const argv = ["run", "adws/adw_frontier.py", ...splitArgs(args)];
      const startedAt = Date.now();
      const RUN_AGENTS = ["gatekeeper", "builder", "reviewer"];
      let out = "";
      let wave: number[] = [];
      const byTicket = new Map<number, { adw: string; flow: Flow }>();

      child = spawn("uv", argv, { cwd: ctx.cwd, stdio: ["ignore", "pipe", "pipe"] });
      const absorb = (b: Buffer) => {
        const text = b.toString();
        out += text;
        for (const line of text.split("\n")) {
          const par = line.match(/\[mill\] ticket=(\d+) adw=([0-9a-f]+) file=(\S+)/);
          // The loop publishes the ticket↔session pair BEFORE spawning the
          // children — with three of them writing to the same stdout, each
          // one's `adw_id:` would arrive interleaved and there would be no way
          // to tell whose it is.
          if (par) {
            const n = Number(par[1]);
            byTicket.set(n, { adw: par[2]!, flow: flow(`#${par[1]} ${par[3]!.replace(/\.md$/, "")}`) });
          }
          const newWave = line.match(/wave:.*?\[([\d, ]*)\]/);
          if (newWave) {
            wave = newWave[1]!.split(",").map((x) => Number(x.trim())).filter(Boolean);
            // A new wave starts the screen from scratch: keeping the previous
            // one would mix already-integrated tickets with running ones.
            for (const n of [...byTicket.keys()]) if (!wave.includes(n)) byTicket.delete(n);
          }
        }
      };
      child.stdout?.on("data", absorb);
      child.stderr?.on("data", absorb);

      const timer = setInterval(() => {
        for (const { adw, flow: f } of byTicket.values()) {
          for (const agent of RUN_AGENTS) {
            drain(path.join(ctx.cwd, SESSIONS, adw, agent, "raw_output.jsonl"), f);
          }
        }
        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        ctx.ui.setWidget(CUSTOM_TYPE, (_tui: any, theme: any) => {
          const c = new Container();
          c.addChild(new Text(
            theme.fg("customMessageLabel", theme.bold("MILL · frontier")) +
            theme.fg("dim", `  ${fmt(elapsed)}${wave.length ? ` · wave [${wave.join(", ")}]` : ""}`),
            1, 0));
          c.addChild(new Text("", 0, 0));
          c.addChild({
            render: (width: number) => safeLines(((): string[] => {
              const cols = [...byTicket.values()].map((v) => v.flow);
              // No ticket identified yet (the loop is computing the wave, or
              // running with --parallel 1): fall back to the raw output, which
              // is what exists.
              if (!cols.length) {
                return out.split("\n").filter((l) => l.trim()).slice(-MAX_LINES)
                  .map((l) => theme.fg("dim", truncateToWidth(`  ${l.trim()}`, width)));
              }
              if (cols.length === 1) return box(cols[0]!, width, theme, ctx.cwd);
              const colW = Math.floor((width - 3 * (cols.length - 1)) / cols.length);
              const rendered = cols.map((f) => box(f, colW, theme, ctx.cwd));
              const heights = Math.max(...rendered.map((d) => d.length));
              const lines: string[] = [];
              for (let i = 0; i < heights; i++) {
                lines.push(rendered
                  .map((d) => {
                    const t = truncateToWidth(d[i] ?? "", colW);
                    return t + " ".repeat(Math.max(0, colW - visibleWidth(t)));
                  })
                  .join("   "));
              }
              return lines;
            })(), width),
          } as any);
          return c;
        });
      }, TICK_MS);

      const code = await new Promise<number>((res) => child!.on("exit", (c) => res(c ?? 1)));
      clearInterval(timer);
      ctx.ui.setWidget(CUSTOM_TYPE, undefined);
      child = undefined;
      pi.sendMessage({
        customType: CUSTOM_TYPE,
        content: (code === 0 ? "**Frontier empty—all tickets are complete.**"
                             : "**The loop stopped.** A ticket failed, did not integrate, or the graph does not close.") +
          `\n\n\`\`\`\n${out.split("\n").filter((l) => l.trim()).slice(-30).join("\n")}\n\`\`\``,
        display: true,
      });
    },
  });

  // ── THE TOOL: the same flow, but triggerable by the MODEL ──
  //
  // Without this, the live screen only existed when the ENGINEER typed the
  // slash command. Pi gives the model `read, bash, edit, write` and nothing
  // else — there is no slash-command tool — so the skill, when it was driving
  // the conversation and decided to trigger a stage, only had `bash`. And
  // `bash` does not pass through the extension: the ADW ran correctly and the
  // panel never appeared.
  //
  // Registering a tool makes both paths converge: you type `/spec`, or the
  // skill calls `mill`, and either way it is the same `runAdw` that draws.
  const SHAPES: Record<string, (a: string[]) => Shape> = {
    research:   (a) => ({ argv: ["adws/adw_research_fusion.py", ...a],
                          cols: ["researcher_a", "researcher_b"], closer: "architect",
                          label: "divergent research" }),
    investigate: (a) => ({ argv: ["adws/adw_research_fusion.py", ...a, "--question"],
                          cols: ["researcher_a", "researcher_b"], closer: "architect",
                          label: "investigating" }),
    spec:       (a) => ({ argv: ["adws/adw_spec.py", ...a], cols: ["speccer"],
                          label: "spec", joins: true }),
    tickets:    (a) => ({ argv: ["adws/adw_tickets.py", ...a], cols: ["slicer"],
                          label: "tickets", joins: true }),
    run:        (a) => ({ argv: ["adws/adw_run.py", ...a],
                          cols: ["gatekeeper", "builder"], closer: "reviewer", label: "run" }),
  };

  pi.registerTool({
    name: "mill",
    label: "Mill",
    description:
      "Triggers a Mill stage and shows the agents working live. " +
      "USE THIS rather than running `uv run adws/...` through Bash: only this route shows the engineer " +
      "the panel and automatically joins the prior session (--adw-id). " +
      "Stages: research (vague idea), investigate (one question), spec, tickets, run (one ticket).",
    promptSnippet: "mill — triggers a Mill stage (research | investigate | spec | tickets | run)",
    parameters: Type.Object({
      flow: Type.Union(
        [Type.Literal("research"), Type.Literal("investigate"), Type.Literal("spec"),
         Type.Literal("tickets"), Type.Literal("run")],
        { description: "stage to trigger" }),
      args: Type.Array(Type.String(), {
        description: 'arguments in the ADW `Usage:` form. For example: ["an idea", "--title", "feature-name"]',
      }),
    }),
    // Sequential: two stages at once would fight over the same widget, and the
    // second would erase the first from the screen without erasing it from the
    // process table.
    executionMode: "sequential",
    execute: async (_id, params: any, _signal, _onUpdate, ctx: any) => {
      const build = SHAPES[params.flow];
      if (!build) {
        return { content: [{ type: "text" as const, text: `unknown stage: ${params.flow}` }],
                 isError: true };
      }
      const args = params.flow === "run"
        ? resolveTicket(ctx.cwd, params.args ?? [])
        : (params.args ?? []);
      const r = await runAdw(ctx, build(args));
      const text = r.ok
        ? `${params.flow} completed · adw_id ${r.adwId}\n\n${r.tail}`
        : `${params.flow} FAILED · adw_id ${r.adwId || "(none)"}\n\n${r.tail}`;
      // `content: [{type:"text"}]`, and NOT `{output}`.
      //
      // Pi renders the result with `result.content.filter(...)`: returning any
      // other shape makes `undefined.filter` blow up inside its TUI and brings
      // down the whole session — after the work succeeded, which is the
      // cruellest moment to lose the conversation. It happened at the end of a
      // 16-minute research run.
      return { content: [{ type: "text" as const, text: text }], isError: !r.ok };
    },
  });

  // ── 7. stop ──
  pi.registerCommand("stop", {
    description: "Stops the running flow. Already committed work remains; the trace on disk stays intact.",
    handler: async (_args, ctx) => {
      if (!child) return ctx.ui.notify("mill: nothing is running", "info");
      child.kill("SIGTERM");
      ctx.ui.notify("mill: flow interrupted", "warn");
    },
  });
}

/**
 * `/run 1`, `/run ticket 1`, `/run 01-slug.md` → the ticket's path.
 *
 * The ADW wants a path and nothing else. But nobody thinks in paths right after
 * reading a numbered list — they think "the one". Requiring
 * `.scratch/<feature>/issues/01-operational-routing-policy.md` typed by hand is
 * requiring the engineer to be an index, and they already have one: the number.
 *
 * Returns the args untouched when a `.md` is already there — whoever passed a
 * path knew what they wanted.
 */
function resolveTicket(cwd: string, args: string[]): string[] {
  if (args.some((a) => a.endsWith(".md"))) return args;

  const flags = args.filter((a) => a.startsWith("--"));
  const number = args.map((a) => a.match(/^(\d{1,3})$/)?.[1]).find(Boolean);
  if (!number) return args;

  const issues = path.join(cwd, ".scratch");
  const found: string[] = [];
  const walk = (dir: string, depth: number) => {
    if (depth > 3) return;
    let entries: fs.Dirent[];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) walk(full, depth + 1);
      else if (e.isFile() && new RegExp(`^0*${number}-.*\\.md$`).test(e.name)) found.push(full);
    }
  };
  walk(issues, 0);

  if (found.length === 1) return [path.relative(cwd, found[0]!), ...flags];
  // Zero or many: return it as it came, and the ADW complains with the path in
  // hand — better an error from the owner of the format than a guess of mine
  // about which feature was meant.
  return args;
}

/** `"text with spaces" --flag value` → argv, respecting quotes. */
function splitArgs(line: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line))) out.push(m[1] ?? m[2] ?? m[3] ?? "");
  return out;
}
