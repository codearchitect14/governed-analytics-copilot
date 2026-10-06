import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../../lib/http";
import { Button, Card, EmptyState, Skeleton } from "../../components/ui";

interface Metric {
  name: string;
  label: string;
  description: string;
  synonyms: string[];
}
interface Dimension {
  name: string;
  synonyms: string[];
  values: string[];
}
interface Session {
  id: string;
  title: string;
  created_at: string;
}
interface Saved {
  id: string;
  title: string;
  question: string;
  created_at: string;
}

function matches(text: string, term: string): boolean {
  return term === "" || text.toLowerCase().includes(term.toLowerCase());
}

export function CatalogPage() {
  const [params, setParams] = useSearchParams();
  const term = params.get("q") ?? "";
  const navigate = useNavigate();
  const metrics = useQuery({ queryKey: ["catalog", "metrics"], queryFn: () => apiJson<Metric[]>("/api/v1/catalog/metrics") });
  const dims = useQuery({ queryKey: ["catalog", "dimensions"], queryFn: () => apiJson<Dimension[]>("/api/v1/catalog/dimensions") });

  const shownMetrics = (metrics.data ?? []).filter((m) => matches(`${m.label} ${m.description} ${m.synonyms.join(" ")}`, term));
  const shownDims = (dims.data ?? []).filter((d) => matches(`${d.name} ${d.synonyms.join(" ")} ${d.values.join(" ")}`, term));

  return (
    <div className="grid gap-6">
      <header>
        <h1 className="text-2xl">Catalog</h1>
        <p className="text-sm text-ink-muted">The metrics and dimensions you can ask about, with their definitions and synonyms.</p>
      </header>
      <div>
        <label htmlFor="catalog-search" className="text-sm font-semibold">Filter the catalog</label>
        <input id="catalog-search" type="search" value={term} onChange={(event) => setParams(event.target.value ? { q: event.target.value } : {})} className="mt-1 min-h-11 w-full max-w-md rounded-md border border-line bg-page px-3" />
      </div>
      {metrics.isPending ? <Skeleton className="h-40 w-full" /> : null}
      <section aria-labelledby="metrics-heading" className="grid gap-3">
        <h2 id="metrics-heading" className="text-lg">Metrics</h2>
        {shownMetrics.length === 0 && metrics.data ? <EmptyState title="No metrics match">Try another word.</EmptyState> : null}
        <div className="grid gap-3 md:grid-cols-2">
          {shownMetrics.map((metric) => (
            <Card key={metric.name}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-base">{metric.label}</h3>
                <Button variant="ghost" onClick={() => navigate("/app/chat", { state: { prefill: `${metric.label} by month` } })}>Ask</Button>
              </div>
              <p className="mt-2 text-sm text-ink-muted">{metric.description}</p>
              <p className="mt-2 text-xs text-ink-muted">Also called: {metric.synonyms.join(", ")}</p>
            </Card>
          ))}
        </div>
      </section>
      <section aria-labelledby="dims-heading" className="grid gap-3">
        <h2 id="dims-heading" className="text-lg">Dimensions</h2>
        <ul className="grid gap-3 md:grid-cols-2">
          {shownDims.map((dim) => (
            <li key={dim.name}>
              <Card>
                <h3 className="text-sm font-semibold">{dim.name.replace(/__/g, " · ").replace(/_/g, " ")}</h3>
                <p className="mt-1 text-xs text-ink-muted">Also called: {dim.synonyms.join(", ")}</p>
                {dim.values.length ? <p className="mt-1 text-xs text-ink-muted">Values: {dim.values.join(", ")}</p> : null}
              </Card>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export function HistoryPage() {
  const navigate = useNavigate();
  const [openId, setOpenId] = useState<string | null>(null);
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => apiJson<Session[]>("/api/v1/chat/sessions") });
  const detail = useQuery({
    queryKey: ["session", openId],
    queryFn: () => apiJson<{ title: string; messages: { role: string; content: Record<string, unknown> }[] }>(`/api/v1/chat/sessions/${openId}`),
    enabled: openId !== null,
  });

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
      <section aria-labelledby="history-heading" className="grid content-start gap-3">
        <h1 id="history-heading" className="text-2xl">History</h1>
        {sessions.isPending ? <Skeleton className="h-40 w-full" /> : null}
        {sessions.data?.length === 0 ? <EmptyState title="No conversations yet">Questions you ask in the chat appear here.</EmptyState> : null}
        <ul className="grid gap-2">
          {(sessions.data ?? []).map((session) => (
            <li key={session.id}>
              <button type="button" onClick={() => setOpenId(session.id)} className="w-full min-h-11 rounded-md border border-line p-3 text-left hover:bg-panel" aria-pressed={openId === session.id}>
                <span className="block font-semibold">{session.title}</span>
                <span className="block text-xs text-ink-muted">{new Date(session.created_at).toLocaleString()}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section aria-live="polite" aria-label="Selected conversation" className="grid content-start gap-3">
        {openId === null ? <EmptyState title="Choose a conversation">Its questions and answer summaries appear here.</EmptyState> : null}
        {detail.data?.messages.map((message, index) => (
          <div key={index} className={`rounded-md p-3 text-sm ${message.role === "user" ? "ml-auto max-w-[80%] bg-brand text-on-brand" : "border border-line"}`}>
            {message.role === "user" ? String(message.content.question ?? "") : `${String(message.content.decision ?? "")}: ${String(message.content.answer ?? "")}`}
          </div>
        ))}
        {openId ? <div><Button variant="secondary" onClick={() => navigate("/app/chat")}>Open the chat</Button></div> : null}
      </section>
    </div>
  );
}

export function SavedPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const saved = useQuery({ queryKey: ["saved"], queryFn: () => apiJson<Saved[]>("/api/v1/saved-queries") });
  const remove = useMutation({
    mutationFn: (id: string) => apiJson(`/api/v1/saved-queries/${id}`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["saved"] }),
  });

  async function rerun(id: string) {
    const body = await apiJson<{ question: string }>(`/api/v1/saved-queries/${id}/run`, { method: "POST" });
    navigate("/app/chat", { state: { prefill: body.question } });
  }

  return (
    <div className="grid gap-4">
      <header>
        <h1 className="text-2xl">Saved questions</h1>
        <p className="text-sm text-ink-muted">Rerunning a question applies your current access rules to the current data.</p>
      </header>
      {saved.isPending ? <Skeleton className="h-40 w-full" /> : null}
      {saved.data?.length === 0 ? <EmptyState title="Nothing saved yet">Use Save question under an answer.</EmptyState> : null}
      <ul className="grid gap-3">
        {(saved.data ?? []).map((item) => (
          <li key={item.id}>
            <Card className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-semibold">{item.title}</p>
                <p className="text-sm text-ink-muted">{item.question}</p>
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => void rerun(item.id)}>Rerun</Button>
                <Button variant="ghost" onClick={() => remove.mutate(item.id)}>Delete</Button>
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
