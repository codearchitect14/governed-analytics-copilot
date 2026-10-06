import { useState, type FormEvent } from "react";
import ReactECharts from "../../lib/echarts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiJson } from "../../lib/http";
import { Badge, Button, Card, EmptyState, KpiCard, Skeleton } from "../../components/ui";
import { downloadText, formatNumber } from "../../lib/util";

// ---- audit explorer -------------------------------------------------------------------------------

interface AuditRow {
  id: number;
  ts: string;
  event: string;
  user_id: string | null;
  role: string | null;
  route: string | null;
  decision: string;
  denial_reason: string | null;
  question: string | null;
  provider: string | null;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  total_ms: number | null;
  final_sql: string | null;
  is_synthetic: boolean;
}
interface AuditPageData {
  total: number;
  limit: number;
  offset: number;
  items: AuditRow[];
}

const DECISIONS = ["", "allowed", "denied", "clarify", "error", "info"] as const;
const ROUTES = ["", "cache", "semantic_cache", "rule", "llm_plan", "llm_sql", "none"] as const;

export function AuditPage() {
  const [filters, setFilters] = useState({ q: "", decision: "", route: "", role: "", date_from: "", date_to: "" });
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AuditRow | null>(null);
  const limit = 25;

  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);

  const rows = useQuery({ queryKey: ["audit", params.toString()], queryFn: () => apiJson<AuditPageData>(`/api/v1/admin/audit?${params.toString()}`) });
  const verify = useQuery({
    queryKey: ["audit", "verify"],
    queryFn: () => apiJson<{ ok: boolean; rows_checked: number; reason: string | null }>("/api/v1/admin/audit/verify"),
    staleTime: 60_000,
  });

  async function exportCsv() {
    const csvParams = new URLSearchParams({ format: "csv" });
    for (const [key, value] of Object.entries(filters)) if (value) csvParams.set(key, value);
    const response = await apiFetch(`/api/v1/admin/audit?${csvParams.toString()}`);
    if (response.ok) downloadText("audit-log.csv", await response.text());
  }

  return (
    <div className="grid gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl">Audit explorer</h1>
          <p className="text-sm text-ink-muted">Every request and security event. Filter, inspect, and export.</p>
        </div>
        <div className="flex items-center gap-2">
          {verify.data ? (
            <Badge tone={verify.data.ok ? "ok" : "error"}>
              {verify.data.ok ? `Chain intact (${verify.data.rows_checked} rows)` : `Chain broken: ${verify.data.reason}`}
            </Badge>
          ) : null}
          <Button variant="secondary" onClick={() => void exportCsv()}>Export CSV</Button>
        </div>
      </header>

      <form className="grid gap-3 rounded-lg border border-line bg-panel p-4 sm:grid-cols-2 lg:grid-cols-6" aria-label="Audit filters" onSubmit={(event: FormEvent) => event.preventDefault()}>
        <div className="flex flex-col gap-1 lg:col-span-2"><label htmlFor="a-q" className="text-sm font-semibold">Search question or reason</label><input id="a-q" className="min-h-11 rounded-md border border-line bg-page px-3" value={filters.q} onChange={(e) => { setOffset(0); setFilters({ ...filters, q: e.target.value }); }} /></div>
        <div className="flex flex-col gap-1"><label htmlFor="a-dec" className="text-sm font-semibold">Decision</label><select id="a-dec" className="min-h-11 rounded-md border border-line bg-page px-3" value={filters.decision} onChange={(e) => { setOffset(0); setFilters({ ...filters, decision: e.target.value }); }}>{DECISIONS.map((d) => <option key={d} value={d}>{d || "Any"}</option>)}</select></div>
        <div className="flex flex-col gap-1"><label htmlFor="a-route" className="text-sm font-semibold">Route</label><select id="a-route" className="min-h-11 rounded-md border border-line bg-page px-3" value={filters.route} onChange={(e) => { setOffset(0); setFilters({ ...filters, route: e.target.value }); }}>{ROUTES.map((r) => <option key={r} value={r}>{r || "Any"}</option>)}</select></div>
        <div className="flex flex-col gap-1"><label htmlFor="a-from" className="text-sm font-semibold">From</label><input id="a-from" type="date" className="min-h-11 rounded-md border border-line bg-page px-3" value={filters.date_from} onChange={(e) => { setOffset(0); setFilters({ ...filters, date_from: e.target.value }); }} /></div>
        <div className="flex flex-col gap-1"><label htmlFor="a-to" className="text-sm font-semibold">To</label><input id="a-to" type="date" className="min-h-11 rounded-md border border-line bg-page px-3" value={filters.date_to} onChange={(e) => { setOffset(0); setFilters({ ...filters, date_to: e.target.value }); }} /></div>
      </form>

      {rows.isPending ? <Skeleton className="h-64 w-full" /> : null}
      {rows.data && rows.data.items.length === 0 ? <EmptyState title="No entries match these filters" /> : null}
      {rows.data && rows.data.items.length > 0 ? (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full min-w-[720px] text-left text-sm" aria-label="Audit entries">
            <thead className="bg-panel"><tr><th scope="col" className="p-3">Time</th><th scope="col">Role</th><th scope="col">Route</th><th scope="col">Decision</th><th scope="col">Question</th><th scope="col">Latency</th><th scope="col"><span className="sr-only">Details</span></th></tr></thead>
            <tbody>
              {rows.data.items.map((row) => (
                <tr key={row.id} className="border-t border-line">
                  <td className="p-3 whitespace-nowrap">{new Date(row.ts).toLocaleString()}</td>
                  <td>{row.role ?? "n/a"}</td>
                  <td>{row.route ?? "n/a"}</td>
                  <td><Badge tone={row.decision === "allowed" ? "ok" : row.decision === "error" ? "error" : "neutral"}>{row.decision}</Badge>{row.is_synthetic ? <span className="ml-2 text-xs text-ink-muted">demo</span> : null}</td>
                  <td className="max-w-xs truncate">{row.question ?? row.event}</td>
                  <td>{row.total_ms !== null ? `${row.total_ms} ms` : "n/a"}</td>
                  <td><Button variant="ghost" onClick={() => setSelected(row)} aria-label={`Details for entry ${row.id}`}>Details</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {rows.data ? (
        <div className="flex items-center justify-between text-sm">
          <span>{offset + 1}–{Math.min(offset + limit, rows.data.total)} of {rows.data.total}</span>
          <div className="flex gap-2">
            <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</Button>
            <Button variant="secondary" disabled={offset + limit >= rows.data.total} onClick={() => setOffset(offset + limit)}>Next</Button>
          </div>
        </div>
      ) : null}

      {selected ? (
        <section role="dialog" aria-modal="false" aria-labelledby="detail-title" className="rounded-lg border border-line bg-panel p-6 shadow-2">
          <div className="flex items-center justify-between">
            <h2 id="detail-title" className="text-lg">Entry {selected.id}</h2>
            <Button variant="ghost" onClick={() => setSelected(null)}>Close</Button>
          </div>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-ink-muted">Question</dt><dd>{selected.question ?? "n/a"}</dd></div>
            <div><dt className="text-ink-muted">Reason</dt><dd>{selected.denial_reason ?? "n/a"}</dd></div>
            <div><dt className="text-ink-muted">Provider and model</dt><dd>{selected.provider ? `${selected.provider} ${selected.model ?? ""}` : "none"}</dd></div>
            <div><dt className="text-ink-muted">Tokens in / out</dt><dd>{selected.tokens_in ?? 0} / {selected.tokens_out ?? 0}</dd></div>
          </dl>
          <pre className="mt-4 overflow-x-auto rounded-md border border-line p-3 text-xs" aria-label="Final SQL">{selected.final_sql ?? "No SQL was run."}</pre>
        </section>
      ) : null}
    </div>
  );
}

// ---- users and roles ------------------------------------------------------------------------------

interface UserRow {
  id: string;
  email: string;
  full_name: string;
  role: string;
  scopes: Record<string, unknown>;
  is_active: boolean;
  locked_until: string | null;
}
interface RoleRow {
  name: string;
  description: string;
  policy_version: number;
}

export function UsersPage() {
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => apiJson<UserRow[]>("/api/v1/admin/users?limit=200") });
  const roles = useQuery({ queryKey: ["admin", "roles"], queryFn: () => apiJson<RoleRow[]>("/api/v1/admin/roles") });
  const [form, setForm] = useState({ email: "", full_name: "", password: "", role: "analyst", regions: "", categories: "", seller_id: "" });
  const [formError, setFormError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => {
      const scopes: Record<string, unknown> = {};
      if (form.regions) scopes.regions = form.regions.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
      if (form.categories) scopes.categories = form.categories.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
      if (form.seller_id) scopes.seller_id = form.seller_id.trim();
      return apiJson("/api/v1/admin/users", { method: "POST", body: JSON.stringify({ email: form.email, full_name: form.full_name, password: form.password, role: form.role, scopes }) });
    },
    onSuccess: () => {
      setFormError(null);
      setForm({ ...form, email: "", full_name: "", password: "" });
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (error: Error) => setFormError(error.message),
  });
  const update = useMutation({
    mutationFn: (input: { id: string; body: Record<string, unknown> }) => apiJson(`/api/v1/admin/users/${input.id}`, { method: "PATCH", body: JSON.stringify(input.body) }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "users"] }),
  });

  return (
    <div className="grid gap-6">
      <header><h1 className="text-2xl">Users and roles</h1><p className="text-sm text-ink-muted">Create accounts, assign roles and scopes, and disable or unlock accounts.</p></header>

      <Card>
        <h2 className="mb-3 text-lg">Create a user</h2>
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); create.mutate(); }} aria-label="Create user">
          <div className="flex flex-col gap-1"><label htmlFor="u-email" className="text-sm font-semibold">Email</label><input id="u-email" type="email" required className="min-h-11 rounded-md border border-line bg-page px-3" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><label htmlFor="u-name" className="text-sm font-semibold">Full name</label><input id="u-name" required className="min-h-11 rounded-md border border-line bg-page px-3" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><label htmlFor="u-pass" className="text-sm font-semibold">Temporary password (12 or more characters)</label><input id="u-pass" type="password" minLength={12} required className="min-h-11 rounded-md border border-line bg-page px-3" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><label htmlFor="u-role" className="text-sm font-semibold">Role</label><select id="u-role" className="min-h-11 rounded-md border border-line bg-page px-3" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{(roles.data ?? []).map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}</select></div>
          <div className="flex flex-col gap-1"><label htmlFor="u-regions" className="text-sm font-semibold">Regions (comma separated state codes)</label><input id="u-regions" className="min-h-11 rounded-md border border-line bg-page px-3" value={form.regions} onChange={(e) => setForm({ ...form, regions: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><label htmlFor="u-cats" className="text-sm font-semibold">Categories (comma separated)</label><input id="u-cats" className="min-h-11 rounded-md border border-line bg-page px-3" value={form.categories} onChange={(e) => setForm({ ...form, categories: e.target.value })} /></div>
          <div className="flex flex-col gap-1"><label htmlFor="u-seller" className="text-sm font-semibold">Seller id</label><input id="u-seller" className="min-h-11 rounded-md border border-line bg-page px-3" value={form.seller_id} onChange={(e) => setForm({ ...form, seller_id: e.target.value })} /></div>
          {formError ? <p role="alert" className="text-sm text-error sm:col-span-2">{formError}</p> : null}
          <div className="sm:col-span-2"><Button type="submit" variant="accent" disabled={create.isPending}>Create user</Button></div>
        </form>
      </Card>

      {users.isPending ? <Skeleton className="h-40 w-full" /> : null}
      {users.data ? (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full min-w-[640px] text-left text-sm" aria-label="Users">
            <thead className="bg-panel"><tr><th scope="col" className="p-3">Name</th><th scope="col">Email</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {users.data.map((user) => (
                <tr key={user.id} className="border-t border-line">
                  <td className="p-3">{user.full_name}</td>
                  <td>{user.email}</td>
                  <td>
                    <label className="sr-only" htmlFor={`role-${user.id}`}>Role for {user.email}</label>
                    <select id={`role-${user.id}`} className="min-h-11 rounded-md border border-line bg-page px-2" value={user.role} onChange={(e) => update.mutate({ id: user.id, body: { role: e.target.value } })}>
                      {(roles.data ?? []).map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
                    </select>
                  </td>
                  <td><Badge tone={user.is_active ? "ok" : "error"}>{user.is_active ? "Active" : "Disabled"}</Badge>{user.locked_until ? <span className="ml-2 text-xs text-warn">Locked</span> : null}</td>
                  <td className="flex flex-wrap gap-2 p-2">
                    <Button variant="ghost" onClick={() => update.mutate({ id: user.id, body: { is_active: !user.is_active } })}>{user.is_active ? "Disable" : "Enable"}</Button>
                    {user.locked_until ? <Button variant="ghost" onClick={() => update.mutate({ id: user.id, body: { unlock: true } })}>Unlock</Button> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

// ---- operations -----------------------------------------------------------------------------------

interface OpsSummary {
  days: number;
  requests: number;
  allowed: number;
  denied: number;
  errors: number;
  success_rate: number | null;
  denial_rate: number | null;
  cache_hit_rate: number | null;
  route_mix: { route: string; requests: number }[];
  requests_per_day: { day: string; requests: number; allowed: number; failed: number }[];
  latency_ms: { p50: number | null; p95: number | null };
  failure_categories: { decision: string; reason: string; requests: number }[];
  most_asked: { question: string; asked: number }[];
  tokens_by_provider: { provider: string; synthetic: boolean; requests: number; tokens_in: number; tokens_out: number }[];
  tokens_saved_estimate: number;
  provider_budgets: { provider: string; model: string; circuit_open: boolean; requests_remaining_day: number; tokens_remaining_day: number }[];
  demo_data: boolean;
  synthetic_rows: number;
}
interface LlmStatus {
  mode: string;
  providers: unknown[];
}

const pct = (value: number | null) => (value === null ? "n/a" : `${(value * 100).toFixed(1)}%`);

export function OperationsPage() {
  const [days, setDays] = useState(30);
  const queryClient = useQueryClient();
  const summary = useQuery({ queryKey: ["ops", "summary", days], queryFn: () => apiJson<OpsSummary>(`/api/v1/admin/ops/summary?days=${days}`) });
  const llm = useQuery({ queryKey: ["ops", "llm"], queryFn: () => apiJson<LlmStatus>("/api/v1/admin/llm") });
  const setMode = useMutation({
    mutationFn: (mode: string) => apiJson<LlmStatus>("/api/v1/admin/llm/mode", { method: "PUT", body: JSON.stringify({ mode }) }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["ops", "llm"] }),
  });

  if (summary.isPending) return <Skeleton className="h-64 w-full" />;
  if (summary.isError) return <EmptyState title="Operations data could not be loaded">{summary.error.message}</EmptyState>;
  const data = summary.data;

  return (
    <div className="grid gap-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl">Operations</h1>
          {data.demo_data ? <Badge tone="warn">Demo data: {formatNumber(data.synthetic_rows)} synthetic rows included</Badge> : null}
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="ops-days" className="text-sm">Period</label>
          <select id="ops-days" className="min-h-11 rounded-md border border-line bg-page px-3" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard label="Requests" value={formatNumber(data.requests)} />
        <KpiCard label="Success rate" value={pct(data.success_rate)} />
        <KpiCard label="Denial rate" value={pct(data.denial_rate)} />
        <KpiCard label="Cache hit rate" value={pct(data.cache_hit_rate)} />
        <KpiCard label="Latency p50" value={data.latency_ms.p50 === null ? "n/a" : `${data.latency_ms.p50} ms`} />
        <KpiCard label="Latency p95" value={data.latency_ms.p95 === null ? "n/a" : `${data.latency_ms.p95} ms`} />
        <KpiCard label="Tokens saved (estimate)" value={formatNumber(data.tokens_saved_estimate)} note="Cache hits times the average model call" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-lg">Requests per day</h2>
          <div role="img" aria-label="Requests per day" className="h-64">
            <ReactECharts notMerge style={{ height: "100%" }} option={{ tooltip: { trigger: "axis" }, legend: { data: ["Allowed", "Failed"] }, xAxis: { type: "category", data: data.requests_per_day.map((d) => d.day) }, yAxis: { type: "value" }, series: [{ name: "Allowed", type: "bar", stack: "r", data: data.requests_per_day.map((d) => d.allowed) }, { name: "Failed", type: "bar", stack: "r", data: data.requests_per_day.map((d) => d.failed) }] }} />
          </div>
        </Card>
        <Card>
          <h2 className="mb-2 text-lg">Route mix</h2>
          <div role="img" aria-label="Route mix of allowed answers" className="h-64">
            <ReactECharts notMerge style={{ height: "100%" }} option={{ tooltip: { trigger: "item" }, series: [{ type: "pie", radius: ["40%", "70%"], data: data.route_mix.map((r) => ({ name: r.route, value: r.requests })) }] }} />
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-lg">Failure categories</h2>
          {data.failure_categories.length === 0 ? <p className="text-sm text-ink-muted">No denials or errors in this period.</p> : (
            <table className="w-full text-left text-sm"><thead><tr><th scope="col">Decision</th><th scope="col">Reason</th><th scope="col">Count</th></tr></thead>
              <tbody>{data.failure_categories.map((f, i) => <tr key={i} className="border-t border-line"><td className="py-2">{f.decision}</td><td>{f.reason}</td><td>{f.requests}</td></tr>)}</tbody></table>
          )}
        </Card>
        <Card>
          <h2 className="mb-2 text-lg">Most asked</h2>
          {data.most_asked.length === 0 ? <p className="text-sm text-ink-muted">No questions yet.</p> : (
            <ol className="list-decimal pl-5 text-sm">{data.most_asked.map((q) => <li key={q.question} className="py-1">{q.question} <span className="text-ink-muted">({q.asked})</span></li>)}</ol>
          )}
        </Card>
      </div>

      <Card>
        <h2 className="mb-2 text-lg">Tokens by provider</h2>
        <table className="w-full text-left text-sm"><thead><tr><th scope="col">Provider</th><th scope="col">Type</th><th scope="col">Requests</th><th scope="col">Tokens in</th><th scope="col">Tokens out</th></tr></thead>
          <tbody>{data.tokens_by_provider.map((t, i) => <tr key={i} className="border-t border-line"><td className="py-2">{t.provider}</td><td>{t.synthetic ? "Demo" : "Live"}</td><td>{t.requests}</td><td>{t.tokens_in}</td><td>{t.tokens_out}</td></tr>)}</tbody></table>
      </Card>

      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg">Provider budgets and mode</h2>
          <div className="flex items-center gap-2">
            <label htmlFor="llm-mode" className="text-sm">Provider mode</label>
            <select id="llm-mode" className="min-h-11 rounded-md border border-line bg-page px-3" value={llm.data?.mode ?? "auto"} onChange={(e) => setMode.mutate(e.target.value)}>
              <option value="auto">Automatic (Groq, then Gemini)</option>
              <option value="groq_only">Groq only</option>
              <option value="gemini_only">Gemini only</option>
            </select>
          </div>
        </div>
        {data.provider_budgets.length === 0 ? <p className="text-sm text-ink-muted">No model provider is configured on this server.</p> : (
          <ul className="grid gap-3 md:grid-cols-2">
            {data.provider_budgets.map((p) => (
              <li key={p.provider} className="rounded-md border border-line p-3 text-sm">
                <p className="font-semibold">{p.provider} · {p.model}</p>
                <p className="text-ink-muted">Requests left today: {p.requests_remaining_day} · Tokens left today: {formatNumber(p.tokens_remaining_day)}</p>
                {p.circuit_open ? <p className="text-warn">Temporarily paused after an error</p> : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// ---- evaluation -----------------------------------------------------------------------------------

export function EvaluationPage() {
  const runs = useQuery({
    queryKey: ["ops", "evals"],
    queryFn: () => apiJson<{ runs: { id: string; suite: string; model: string | null; prompt_version: string | null; sample_size: number; status: string; started_at: string }[]; note: string | null }>("/api/v1/admin/ops/evals"),
  });
  return (
    <div className="grid gap-4">
      <header><h1 className="text-2xl">Evaluation</h1><p className="text-sm text-ink-muted">Accuracy runs for each model and prompt version.</p></header>
      {runs.isPending ? <Skeleton className="h-40 w-full" /> : null}
      {runs.data && runs.data.runs.length === 0 ? <EmptyState title="No evaluation runs yet">{runs.data.note}</EmptyState> : null}
      {runs.data && runs.data.runs.length > 0 ? (
        <table className="w-full text-left text-sm" aria-label="Evaluation runs"><thead><tr><th scope="col">Started</th><th scope="col">Suite</th><th scope="col">Model</th><th scope="col">Prompt</th><th scope="col">Sample</th><th scope="col">Status</th></tr></thead>
          <tbody>{runs.data.runs.map((r) => <tr key={r.id} className="border-t border-line"><td className="py-2">{new Date(r.started_at).toLocaleString()}</td><td>{r.suite}</td><td>{r.model ?? "n/a"}</td><td>{r.prompt_version ?? "n/a"}</td><td>{r.sample_size}</td><td>{r.status}</td></tr>)}</tbody></table>
      ) : null}
    </div>
  );
}
