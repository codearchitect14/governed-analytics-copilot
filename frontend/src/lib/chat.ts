import { useAuth } from "./auth-store";
import { parseSseBuffer } from "./util";

export interface PipelineStep {
  state: string;
  elapsed_ms: number;
}

export interface AnswerPayload {
  answer_text: string | null;
  route: string | null;
  decision: "allowed" | "clarify" | "denied" | "error";
  plan: Record<string, unknown> | null;
  sql: { generated: string | null; final: string | null } | null;
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
  chart_spec: { type: string; option?: Record<string, unknown>; value?: number | null; metric?: string };
  explanation: string[];
  policy_notes: string[];
  usage: {
    provider: string | null;
    model: string | null;
    tokens_in: number;
    tokens_out: number;
    latency_ms: number;
    model_calls: number;
    prompt_versions: string[];
  };
  clarification: string | null;
  audit_id: number | null;
  steps: string[];
}

export interface StreamHandlers {
  onStep: (step: string, elapsedMs: number) => void;
  onResult: (payload: AnswerPayload) => void;
  onError: (message: string, decision: string, auditId: number | null) => void;
}

/** Streams one question through the pipeline. Resolves when the stream ends. */
export async function streamQuestion(
  question: string,
  sessionId: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = useAuth.getState().accessToken;
  const response = await fetch("/api/v1/chat/query", {
    method: "POST",
    credentials: "same-origin",
    signal,
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ question, session_id: sessionId }),
  });
  if (!response.ok || !response.body) {
    handlers.onError(
      response.status === 429 ? "You are asking questions too quickly. Wait a moment and try again." : "The question could not be sent.",
      "error",
      null,
    );
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseBuffer(buffer);
    buffer = parsed.rest;
    for (const item of parsed.events) {
      const data = item.data as Record<string, unknown>;
      if (item.event === "step") {
        handlers.onStep(String(data.state), Number(data.elapsed_ms));
      } else if (item.event === "result") {
        handlers.onResult(data as unknown as AnswerPayload);
      } else if (item.event === "error") {
        handlers.onError(String(data.message), String(data.decision), (data.audit_id as number | null) ?? null);
      }
    }
  }
}

export const STEP_LABELS: Record<string, string> = {
  resolving: "Resolving the question",
  planning: "Planning",
  generating: "Building the query",
  validating: "Validating",
  applying_policy: "Applying your access rules",
  executing: "Running the query",
  charting: "Choosing a chart",
  done: "Done",
};
