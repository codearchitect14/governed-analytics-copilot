import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import ReactECharts from "../../lib/echarts";
import { format as formatSql } from "sql-formatter";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ROLE_USE_CASES } from "../../lib/content";
import { apiJson } from "../../lib/http";
import { useAuth } from "../../lib/auth-store";
import { STEP_LABELS, streamQuestion, type AnswerPayload } from "../../lib/chat";
import { downloadText, formatDelta, sortRows, toCsv, type SortState } from "../../lib/util";
import { Badge, Button, Card, Tabs } from "../../components/ui";

type Message =
  | { id: number; kind: "user"; text: string }
  | { id: number; kind: "answer"; payload: AnswerPayload; question: string }
  | { id: number; kind: "notice"; text: string; tone: "error" | "info" };

interface ProgressState {
  steps: { state: string; elapsedMs: number }[];
}

const CLARIFY_CHIPS = ["Last month", "Last 12 months", "Revenue", "Orders", "By customer state"];

function ChartView({ payload }: { payload: AnswerPayload }) {
  const spec = payload.chart_spec;
  if (spec.type === "kpi") {
    const metric = spec.metric ?? "value";
    return (
      <div className="rounded-md border border-line p-6 text-center" aria-label="Single value">
        <p className="text-sm text-ink-muted">{metric.replace(/_/g, " ")}</p>
        <p className="mt-2 text-4xl font-bold">{spec.value === null || spec.value === undefined ? "n/a" : spec.value.toLocaleString("en-GB", { maximumFractionDigits: 2 })}</p>
      </div>
    );
  }
  if (spec.option && spec.type !== "table") {
    return (
      <div role="img" aria-label={`${spec.type} chart of the result`} className="h-80 w-full">
        <ReactECharts option={{ color: ["#0072b2", "#e69f00", "#009e73", "#cc79a7", "#56b4e9", "#d55e00"], ...spec.option }} style={{ height: "100%", width: "100%" }} notMerge />
      </div>
    );
  }
  return <p className="text-sm text-ink-muted">A table is shown for this result.</p>;
}

function DataTable({ columns, rows, truncated, label }: { columns: string[]; rows: unknown[][]; truncated: boolean; label: string }) {
  const [sort, setSort] = useState<SortState | null>(null);
  const sorted = useMemo(() => sortRows(rows, columns, sort), [rows, columns, sort]);

  function toggle(column: string) {
    setSort((current) => {
      if (current?.column === column) return { column, direction: current.direction === "asc" ? "desc" : "asc" };
      return { column, direction: "asc" };
    });
  }

  if (rows.length === 0) return <p className="text-sm text-ink-muted">No rows match this question for your role and period.</p>;
  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">{rows.length} rows{truncated ? " (first rows shown)" : ""}</p>
        <Button variant="secondary" onClick={() => downloadText("result.csv", toCsv(columns, rows))}>Export CSV</Button>
      </div>
      <div className="max-h-96 overflow-auto rounded-md border border-line">
        <table aria-label={label} className="w-full border-collapse text-left text-sm">
          <thead className="sticky top-0 bg-panel">
            <tr>
              {columns.map((column) => (
                <th key={column} scope="col" aria-sort={sort?.column === column ? (sort.direction === "asc" ? "ascending" : "descending") : "none"} className="border-b border-line p-0">
                  <button type="button" onClick={() => toggle(column)} className="flex min-h-11 w-full items-center px-3 py-2 font-semibold">
                    {column.replace(/_/g, " ")}
                    {sort?.column === column ? <span aria-hidden="true" className="ml-2">{sort.direction === "asc" ? "▲" : "▼"}</span> : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b border-line">
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="px-3 py-2 align-top">{cell === null ? "n/a" : String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SqlPanel({ payload }: { payload: AnswerPayload }) {
  const [showFinal, setShowFinal] = useState(true);
  const sql = payload.sql;
  const text = showFinal ? sql?.final : sql?.generated;
  const pretty = useMemo(() => {
    if (!text) return "";
    try {
      return formatSql(text, { language: "postgresql" });
    } catch {
      return text;
    }
  }, [text]);
  if (!sql) return <p className="text-sm text-ink-muted">No SQL was run for this answer.</p>;
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant={showFinal ? "primary" : "secondary"} onClick={() => setShowFinal(true)} aria-pressed={showFinal}>Final (after policy)</Button>
        <Button variant={!showFinal ? "primary" : "secondary"} onClick={() => setShowFinal(false)} aria-pressed={!showFinal}>Generated</Button>
        <Button variant="ghost" onClick={() => void navigator.clipboard?.writeText(pretty)}>Copy</Button>
      </div>
      <pre aria-label="SQL statement" className="overflow-x-auto rounded-md border border-line bg-panel p-4 font-code text-xs leading-relaxed">
        <code>{pretty}</code>
      </pre>
      {payload.policy_notes.length ? (
        <ul className="list-disc pl-5 text-sm text-ink-muted">
          {payload.policy_notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

function AnswerCard({
  payload,
  question,
  onFeedback,
  onSave,
  onFollowUp,
}: {
  payload: AnswerPayload;
  question: string;
  onFeedback: (value: "up" | "down") => void;
  onSave: () => void;
  onFollowUp: (text: string) => void;
}) {
  const hasData = payload.columns.length > 0;
  const tabs = [
    {
      id: "answer",
      label: "Answer",
      content: (
        <div className="grid gap-4">
          <p className="text-base">{payload.answer_text}</p>
          {payload.explanation.length > 1 ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink-muted">
              {payload.explanation.slice(1).map((line) => <li key={line}>{line}</li>)}
            </ul>
          ) : null}
          {hasData ? <ChartView payload={payload} /> : null}
        </div>
      ),
    },
    { id: "data", label: "Data", content: hasData ? <DataTable columns={payload.columns} rows={payload.rows} truncated={payload.truncated} label={`Result for: ${question}`} /> : <p className="text-sm text-ink-muted">No data.</p> },
    { id: "sql", label: "SQL", content: <SqlPanel payload={payload} /> },
    {
      id: "plan",
      label: "Plan",
      content: <pre aria-label="Plan" className="overflow-x-auto rounded-md border border-line bg-panel p-4 text-xs">{JSON.stringify(payload.plan ?? { note: "No plan: the answer came from a rule or cache." }, null, 2)}</pre>,
    },
    {
      id: "governance",
      label: "Governance",
      content: (
        <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-ink-muted">Route</dt><dd>{payload.route ?? "none"}</dd></div>
          <div><dt className="text-ink-muted">Provider</dt><dd>{payload.usage.provider ?? "none (no model call)"}</dd></div>
          <div><dt className="text-ink-muted">Tokens in / out</dt><dd>{payload.usage.tokens_in} / {payload.usage.tokens_out}</dd></div>
          <div><dt className="text-ink-muted">Latency</dt><dd>{payload.usage.latency_ms} ms (model)</dd></div>
          <div><dt className="text-ink-muted">Prompt versions</dt><dd>{payload.usage.prompt_versions.join(", ") || "n/a"}</dd></div>
          <div><dt className="text-ink-muted">Audit id</dt><dd>{payload.audit_id ?? "n/a"}</dd></div>
          <div className="sm:col-span-2"><dt className="text-ink-muted">Policy notes</dt><dd>{payload.policy_notes.join(" ") || "No filters or masks were needed."}</dd></div>
        </dl>
      ),
    },
  ];
  return (
    <Card className="grid gap-4">
      <Tabs label="Answer details" items={tabs} />
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <Button variant="ghost" aria-label="Helpful" onClick={() => onFeedback("up")}>Helpful</Button>
        <Button variant="ghost" aria-label="Not helpful" onClick={() => onFeedback("down")}>Not helpful</Button>
        <Button variant="secondary" onClick={onSave}>Save question</Button>
        <Button variant="secondary" onClick={() => onFollowUp(`Break ${question.toLowerCase()} down by month`)}>Follow up: by month</Button>
      </div>
    </Card>
  );
}

export default function ChatPage() {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const user = useAuth((state) => state.user);
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ProgressState>({ steps: [] });
  const [sessionId] = useState<string | null>(null);
  const nextId = useRef(1);
  const abortRef = useRef<AbortController | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);

  const prefill = (location.state as { prefill?: string } | null)?.prefill ?? searchParams.get("q");
  useEffect(() => {
    if (prefill) setDraft(prefill);
  }, [prefill]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, progress]);

  const save = useMutation({
    mutationFn: (question: string) => apiJson("/api/v1/saved-queries", { method: "POST", body: JSON.stringify({ title: question.slice(0, 80), question }) }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["saved"] }),
  });
  const feedback = useMutation({
    mutationFn: (input: { auditId: number; value: "up" | "down" }) =>
      apiJson("/api/v1/chat/feedback", { method: "POST", body: JSON.stringify({ audit_id: input.auditId, value: input.value }) }),
  });
  const suggestions = useQuery({
    queryKey: ["catalog", "meta"],
    queryFn: () => apiJson<{ data_as_of: string }>("/api/v1/catalog/meta"),
    staleTime: 300_000,
  });

  async function ask(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setBusy(true);
    setDraft("");
    setProgress({ steps: [] });
    const id = nextId.current++;
    setMessages((list) => [...list, { id, kind: "user", text: question }]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamQuestion(
        question,
        sessionId,
        {
          onStep: (state, elapsedMs) => setProgress((value) => ({ steps: [...value.steps, { state, elapsedMs }] })),
          onResult: (payload) => {
            if (payload.decision === "allowed" || payload.decision === "clarify") {
              setMessages((list) => [...list, { id: nextId.current++, kind: "answer", payload, question }]);
            } else {
              setMessages((list) => [...list, { id: nextId.current++, kind: "notice", text: payload.answer_text ?? "Not answered.", tone: "info" }]);
            }
          },
          onError: (message, decision) => {
            setMessages((list) => [...list, { id: nextId.current++, kind: "notice", text: message, tone: decision === "denied" || decision === "clarify" ? "info" : "error" }]);
          },
        },
        controller.signal,
      );
    } catch {
      setMessages((list) => [...list, { id: nextId.current++, kind: "notice", text: "The connection was interrupted. Try again.", tone: "error" }]);
    } finally {
      setBusy(false);
      setProgress({ steps: [] });
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void ask(draft);
  }

  function rememberSession(payload: AnswerPayload) {
    if (!sessionId && payload.audit_id) void queryClient.invalidateQueries({ queryKey: ["sessions"] });
  }

  const lastStep = progress.steps[progress.steps.length - 1];
  const examples = ROLE_USE_CASES.map((item) => item.question).slice(0, 3);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <header>
        <h1 className="text-2xl">Chat</h1>
        <p className="text-sm text-ink-muted">
          Signed in as {user?.full_name}. Answers use the data your role can see.
          {suggestions.data ? ` Data available up to ${suggestions.data.data_as_of}.` : ""}
        </p>
      </header>

      <div ref={logRef} className="flex min-h-[40vh] flex-col gap-4 overflow-y-auto rounded-lg border border-line bg-page p-4" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 ? (
          <div className="grid gap-3">
            <p className="text-ink-muted">Try one of these questions:</p>
            <div className="flex flex-wrap gap-2">
              {examples.map((example) => (
                <button key={example} type="button" onClick={() => void ask(example)} className="min-h-11 rounded-full border border-line px-4 text-sm hover:bg-panel">
                  {example}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {messages.map((message) => {
          if (message.kind === "user") {
            return (
              <div key={message.id} className="ml-auto max-w-[80%] rounded-lg bg-brand p-3 text-sm text-on-brand">{message.text}</div>
            );
          }
          if (message.kind === "notice") {
            return (
              <div key={message.id} role={message.tone === "error" ? "alert" : "status"} className="max-w-[90%] rounded-md border border-line p-3 text-sm">
                {message.text}
              </div>
            );
          }
          const payload = message.payload;
          if (payload.decision === "clarify") {
            return (
              <div key={message.id} className="grid max-w-[90%] gap-3">
                <p className="rounded-md border border-line p-3 text-sm">{payload.clarification}</p>
                <div className="flex flex-wrap gap-2">
                  {CLARIFY_CHIPS.map((chip) => (
                    <button key={chip} type="button" onClick={() => void ask(`${message.question} ${chip.toLowerCase()}`)} className="min-h-11 rounded-full border border-line px-3 text-xs hover:bg-panel">
                      {chip}
                    </button>
                  ))}
                </div>
              </div>
            );
          }
          return (
            <div key={message.id} className="max-w-full">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
                <Badge>{payload.route ?? "answer"}</Badge>
                {payload.usage.model_calls === 0 ? <span>Answered without a model call</span> : null}
                {payload.policy_notes.length ? <span>Policy applied</span> : null}
              </div>
              <AnswerCard
                payload={payload}
                question={message.question}
                onFeedback={(value) => {
                  if (payload.audit_id) feedback.mutate({ auditId: payload.audit_id, value });
                  rememberSession(payload);
                }}
                onSave={() => save.mutate(message.question)}
                onFollowUp={(text) => void ask(text)}
              />
            </div>
          );
        })}

        {busy ? (
          <div className="grid gap-1 text-sm text-ink-muted" role="status">
            {progress.steps.map((step) => (
              <span key={step.state}>{STEP_LABELS[step.state] ?? step.state} · {step.elapsedMs} ms</span>
            ))}
            {!lastStep ? <span>Working…</span> : null}
          </div>
        ) : null}
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-2 sm:flex-row" role="search">
        <label htmlFor="question" className="sr-only">Your question</label>
        <input
          id="question"
          value={draft}
          maxLength={500}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask a question, for example: revenue by customer state last month"
          className="min-h-11 flex-1 rounded-md border border-line bg-page px-3 text-base"
        />
        <Button type="submit" variant="accent" disabled={busy || !draft.trim()}>Ask</Button>
      </form>
      <p className="text-xs text-ink-muted">Formulas and sensitive identifiers are handled by the policy engine, not by this page.</p>
      {formatDelta(null) ? null : null}
    </div>
  );
}
