import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import ReactECharts from "../../lib/echarts";
import { useQuery } from "@tanstack/react-query";
import { apiJson, ApiError } from "../../lib/http";
import { Button, Card, EmptyState, KpiCard, Skeleton, Tabs } from "../../components/ui";
import { downloadText, formatDelta, formatMoney, formatNumber, formatPercent, toCsv } from "../../lib/util";

type Compare = "none" | "previous" | "yoy";
interface Meta {
  data_as_of: string;
}
interface Section<T> {
  available: boolean;
  reason?: string;
  data: T;
}
interface Kpi {
  value: number | null;
  previous?: number | null;
  delta_pct?: number | null;
  sparkline?: number[];
  available?: boolean;
}
interface Overview {
  kpis: Record<string, Kpi>;
  revenue_trend: { month: string; revenue: number; mom_pct: number | null; yoy_pct: number | null; moving_average_3m: number }[];
  revenue_by_category: Section<{ category: string; revenue: number; orders: number }[]>;
  revenue_by_state: Section<{ state: string; revenue: number; orders: number; customers: number }[]>;
  payment_mix: Section<{ payment_type: string; orders: number; value: number }[]>;
  order_status_funnel: Section<{ status: string; orders: number }[]>;
}

const PRESETS = [
  { id: "3m", label: "Last 3 months", months: 3 },
  { id: "6m", label: "Last 6 months", months: 6 },
  { id: "12m", label: "Last 12 months", months: 12 },
  { id: "24m", label: "Last 24 months", months: 24 },
] as const;

function addMonths(date: Date, months: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + months, 1);
}
function iso(date: Date): string {
  return date.toISOString().slice(0, 10);
}

interface Filters {
  preset: (typeof PRESETS)[number]["id"];
  state: string;
  category: string;
  compare: Compare;
}

function useDashboard<T>(section: string, filters: Filters, range: { start: string; end: string }) {
  const params = new URLSearchParams({ start: range.start, end: range.end, compare: filters.compare });
  if (filters.state) params.set("state", filters.state);
  if (filters.category) params.set("category", filters.category);
  return useQuery<T, ApiError>({
    queryKey: ["dashboard", section, range.start, range.end, filters.state, filters.category, filters.compare],
    queryFn: () => apiJson<T>(`/api/v1/dashboard/${section}?${params.toString()}`),
    retry: false,
  });
}

function ChartBox({ option, label, height = 280 }: { option: Record<string, unknown>; label: string; height?: number }) {
  return (
    <div role="img" aria-label={label} style={{ height }} className="w-full">
      <ReactECharts option={{ color: ["#0072b2", "#e69f00", "#009e73", "#cc79a7", "#56b4e9", "#d55e00"], ...option }} style={{ height: "100%" }} notMerge />
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  return (
    <ChartBox
      label="Revenue sparkline"
      height={48}
      option={{ grid: { left: 0, right: 0, top: 4, bottom: 4 }, xAxis: { show: false, type: "category", data: values.map((_, i) => i) }, yAxis: { show: false, type: "value" }, series: [{ type: "line", data: values, symbol: "none", smooth: true }] }}
    />
  );
}

function Loading() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="mt-4 h-64 w-full" />
    </div>
  );
}

function SectionUnavailable({ section }: { section: Section<unknown> }) {
  return <EmptyState title="Not available for your role">{section.reason ?? "This view needs data your role cannot read."}</EmptyState>;
}

function AskButton({ question }: { question: string }) {
  const navigate = useNavigate();
  return (
    <Button variant="ghost" onClick={() => navigate("/app/chat", { state: { prefill: question } })}>
      Ask about this
    </Button>
  );
}

function OverviewTab({ filters, range }: { filters: Filters; range: { start: string; end: string } }) {
  const query = useDashboard<Overview>("overview", filters, range);
  if (query.isPending) return <Loading />;
  if (query.isError) return <EmptyState title="The overview could not be loaded">{query.error.message}</EmptyState>;
  const data = query.data;
  const kpi = data.kpis;
  const compared = filters.compare !== "none";
  return (
    <div className="grid gap-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <KpiCard label="Revenue" value={formatMoney(kpi.revenue.value)} delta={compared ? kpi.revenue.delta_pct : undefined} note="Item prices, excluding canceled orders" />
        <KpiCard label="Orders" value={formatNumber(kpi.orders.value)} delta={compared ? kpi.orders.delta_pct : undefined} />
        <KpiCard label="Average order value" value={formatMoney(kpi.aov.value)} delta={compared ? kpi.aov.delta_pct : undefined} />
        <KpiCard label="Unique customers" value={formatNumber(kpi.unique_customers.value)} delta={compared ? kpi.unique_customers.delta_pct : undefined} />
        <KpiCard label="On time delivery" value={kpi.on_time_delivery_rate.available === false ? "n/a" : formatPercent(kpi.on_time_delivery_rate.value)} note={kpi.on_time_delivery_rate.available === false ? "Not available for your role" : undefined} />
        <KpiCard label="Average review score" value={kpi.avg_review_score.available === false ? "n/a" : formatNumber(kpi.avg_review_score.value ?? undefined, 2)} />
      </div>
      {compared ? <p className="text-sm text-ink-muted">Changes compare with {filters.compare === "yoy" ? "the same period last year" : "the previous period"} ({formatDelta(kpi.revenue.delta_pct)} revenue).</p> : null}
      <Card>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg">Revenue trend</h2>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => downloadText("revenue-trend.csv", toCsv(["month", "revenue", "mom_pct", "yoy_pct", "moving_average_3m"], data.revenue_trend.map((r) => [r.month, r.revenue, r.mom_pct, r.yoy_pct, r.moving_average_3m])))}>CSV</Button>
            <AskButton question="Revenue by month for this period" />
          </div>
        </div>
        {data.revenue_trend.length ? (
          <ChartBox
            label="Monthly revenue with three month moving average"
            option={{
              tooltip: { trigger: "axis" },
              legend: { data: ["Revenue", "3 month average"] },
              xAxis: { type: "category", data: data.revenue_trend.map((r) => r.month) },
              yAxis: { type: "value" },
              series: [
                { name: "Revenue", type: "line", areaStyle: { opacity: 0.15 }, data: data.revenue_trend.map((r) => r.revenue) },
                { name: "3 month average", type: "line", data: data.revenue_trend.map((r) => r.moving_average_3m), lineStyle: { type: "dashed" } },
              ],
            }}
          />
        ) : (
          <EmptyState title="No revenue in this period" />
        )}
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-lg">Revenue by category</h2>
          {data.revenue_by_category.available ? (
            <ChartBox label="Revenue by category" option={{ tooltip: {}, grid: { containLabel: true }, xAxis: { type: "value" }, yAxis: { type: "category", data: data.revenue_by_category.data.map((c) => c.category) }, series: [{ type: "bar", data: data.revenue_by_category.data.map((c) => c.revenue) }] }} />
          ) : (
            <SectionUnavailable section={data.revenue_by_category} />
          )}
        </Card>
        <Card>
          <h2 className="mb-2 text-lg">Revenue by state</h2>
          {data.revenue_by_state.available ? (
            <ChartBox label="Revenue by customer state" option={{ tooltip: {}, grid: { containLabel: true }, xAxis: { type: "category", data: data.revenue_by_state.data.map((s) => s.state) }, yAxis: { type: "value" }, series: [{ type: "bar", data: data.revenue_by_state.data.map((s) => s.revenue) }] }} />
          ) : (
            <SectionUnavailable section={data.revenue_by_state} />
          )}
        </Card>
        <Card>
          <h2 className="mb-2 text-lg">Payment mix</h2>
          {data.payment_mix.available ? (
            <ChartBox label="Payment type share of orders" option={{ tooltip: { trigger: "item" }, series: [{ type: "pie", radius: ["45%", "70%"], data: data.payment_mix.data.map((p) => ({ name: p.payment_type, value: p.orders })) }] }} />
          ) : (
            <SectionUnavailable section={data.payment_mix} />
          )}
        </Card>
        <Card>
          <h2 className="mb-2 text-lg">Order status</h2>
          {data.order_status_funnel.available ? (
            <ChartBox label="Orders by status" option={{ tooltip: {}, grid: { containLabel: true }, xAxis: { type: "value" }, yAxis: { type: "category", data: data.order_status_funnel.data.map((s) => s.status) }, series: [{ type: "bar", data: data.order_status_funnel.data.map((s) => s.orders) }] }} />
          ) : (
            <SectionUnavailable section={data.order_status_funnel} />
          )}
        </Card>
      </div>
      <div className="flex flex-wrap gap-3">
        {Object.entries(kpi).map(([name, value]) =>
          value.sparkline?.length ? <div key={name} className="w-40"><p className="text-xs text-ink-muted">{name.replace(/_/g, " ")}</p><Sparkline values={value.sparkline} /></div> : null,
        )}
      </div>
    </div>
  );
}

interface Sales {
  monthly: { month: string; revenue: number; orders: number }[];
  weekday_hour_heatmap: { weekday: number; hour: number; orders: number; revenue: number }[];
  category_growth: { category: string; revenue: number; previous: number; growth_pct: number | null }[];
  top_products: { product_id: string; category: string; revenue: number; items: number }[];
}

function SalesTab({ filters, range }: { filters: Filters; range: { start: string; end: string } }) {
  const query = useDashboard<Sales>("sales", filters, range);
  const cells = useMemo(() => (query.data?.weekday_hour_heatmap ?? []).map((c) => [c.hour, c.weekday - 1, c.orders]), [query.data]);
  if (query.isPending) return <Loading />;
  if (query.isError) return <EmptyState title="Sales could not be loaded">{query.error.message}</EmptyState>;
  const data = query.data;
  return (
    <div className="grid gap-6">
      <Card>
        <h2 className="mb-2 text-lg">Revenue and orders by month</h2>
        <ChartBox label="Monthly revenue and orders" option={{ tooltip: { trigger: "axis" }, legend: { data: ["Revenue", "Orders"] }, xAxis: { type: "category", data: data.monthly.map((m) => m.month) }, yAxis: [{ type: "value" }, { type: "value" }], series: [{ name: "Revenue", type: "bar", data: data.monthly.map((m) => m.revenue) }, { name: "Orders", type: "line", yAxisIndex: 1, data: data.monthly.map((m) => m.orders) }] }} />
      </Card>
      <Card>
        <h2 className="mb-2 text-lg">Orders by weekday and hour</h2>
        <ChartBox label="Heatmap of orders by weekday and hour" height={320} option={{ tooltip: { position: "top" }, grid: { height: "70%", top: 10 }, xAxis: { type: "category", data: Array.from({ length: 24 }, (_, h) => `${h}:00`), splitArea: { show: true } }, yAxis: { type: "category", data: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], splitArea: { show: true } }, visualMap: { min: 0, max: Math.max(1, ...cells.map((c) => Number(c[2]))), calculable: true, orient: "horizontal", left: "center", bottom: 0 }, series: [{ type: "heatmap", data: cells }] }} />
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-lg">Category growth</h2>
          {data.category_growth.length ? (
            <table className="w-full text-left text-sm" aria-label="Category growth"><thead><tr><th scope="col">Category</th><th scope="col">Revenue</th><th scope="col">Change</th></tr></thead>
              <tbody>{data.category_growth.map((row) => <tr key={row.category} className="border-t border-line"><td className="py-2">{row.category}</td><td>{formatMoney(row.revenue)}</td><td>{formatDelta(row.growth_pct)}</td></tr>)}</tbody></table>
          ) : (
            <EmptyState title="Choose a comparison">Growth needs a previous period. Pick one in the filter bar.</EmptyState>
          )}
        </Card>
        <Card>
          <div className="mb-2 flex items-center justify-between"><h2 className="text-lg">Top products</h2><Button variant="secondary" onClick={() => downloadText("top-products.csv", toCsv(["product_id", "category", "revenue", "items"], data.top_products.map((p) => [p.product_id, p.category, p.revenue, p.items])))}>CSV</Button></div>
          <table className="w-full text-left text-sm" aria-label="Top products"><thead><tr><th scope="col">Product</th><th scope="col">Category</th><th scope="col">Revenue</th><th scope="col">Items</th></tr></thead>
            <tbody>{data.top_products.map((p) => <tr key={p.product_id} className="border-t border-line"><td className="py-2">{p.product_id}</td><td>{p.category}</td><td>{formatMoney(p.revenue)}</td><td>{p.items}</td></tr>)}</tbody></table>
        </Card>
      </div>
    </div>
  );
}

interface Customers {
  new_vs_repeat: { month: string; new: number; repeat: number }[];
  cohort_retention: Section<{ cohort_month: string; months_since: number; cohort_size: number; retention_rate: number }[]>;
  geography: { state: string; customers: number; orders: number; revenue: number }[];
}

function CustomersTab({ filters, range }: { filters: Filters; range: { start: string; end: string } }) {
  const query = useDashboard<Customers>("customers", filters, range);
  if (query.isPending) return <Loading />;
  if (query.isError) return <EmptyState title="Customers could not be loaded">{query.error.message}</EmptyState>;
  const data = query.data;
  return (
    <div className="grid gap-6">
      <Card>
        <h2 className="mb-2 text-lg">New and repeat customers</h2>
        <ChartBox label="New and repeat customers by month" option={{ tooltip: { trigger: "axis" }, legend: { data: ["New", "Repeat"] }, xAxis: { type: "category", data: data.new_vs_repeat.map((m) => m.month) }, yAxis: { type: "value" }, series: [{ name: "New", type: "bar", stack: "c", data: data.new_vs_repeat.map((m) => m.new) }, { name: "Repeat", type: "bar", stack: "c", data: data.new_vs_repeat.map((m) => m.repeat) }] }} />
      </Card>
      <Card>
        <h2 className="mb-2 text-lg">Cohort retention</h2>
        {data.cohort_retention.available ? (
          <div className="overflow-x-auto">
            <table className="text-left text-xs" aria-label="Cohort retention by months since first purchase">
              <thead><tr><th scope="col">Cohort</th>{Array.from({ length: 6 }, (_, i) => <th key={i} scope="col">M{i}</th>)}</tr></thead>
              <tbody>
                {[...new Set(data.cohort_retention.data.map((c) => c.cohort_month))].map((cohort) => (
                  <tr key={cohort} className="border-t border-line">
                    <th scope="row" className="py-1 pr-3 font-normal">{cohort.slice(0, 7)}</th>
                    {Array.from({ length: 6 }, (_, i) => {
                      const cell = data.cohort_retention.data.find((c) => c.cohort_month === cohort && c.months_since === i);
                      return <td key={i} className="px-2 py-1">{cell ? formatPercent(cell.retention_rate) : ""}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <SectionUnavailable section={data.cohort_retention} />
        )}
      </Card>
      <Card>
        <div className="mb-2 flex items-center justify-between"><h2 className="text-lg">Geography</h2><Button variant="secondary" onClick={() => downloadText("geography.csv", toCsv(["state", "customers", "orders", "revenue"], data.geography.map((g) => [g.state, g.customers, g.orders, g.revenue])))}>CSV</Button></div>
        <table className="w-full text-left text-sm" aria-label="Customers and revenue by state"><thead><tr><th scope="col">State</th><th scope="col">Customers</th><th scope="col">Orders</th><th scope="col">Revenue</th></tr></thead>
          <tbody>{data.geography.map((g) => <tr key={g.state} className="border-t border-line"><td className="py-2">{g.state}</td><td>{g.customers}</td><td>{g.orders}</td><td>{formatMoney(g.revenue)}</td></tr>)}</tbody></table>
      </Card>
    </div>
  );
}

interface Logistics {
  delivery_days_distribution: { days: number; orders: number }[];
  estimated_vs_actual: { month: string; actual_days: number; estimated_days: number; late_rate: number }[];
  late_rate_by_state: { state: string; late_rate: number; delivered: number }[];
  freight_share_of_revenue: number | null;
}

function LogisticsTab({ filters, range }: { filters: Filters; range: { start: string; end: string } }) {
  const query = useDashboard<Logistics>("logistics", filters, range);
  if (query.isPending) return <Loading />;
  if (query.isError) return <EmptyState title="Logistics could not be loaded">{query.error.message}</EmptyState>;
  const data = query.data;
  return (
    <div className="grid gap-6">
      <KpiCard label="Freight share of revenue" value={formatPercent(data.freight_share_of_revenue)} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-lg">Delivery days</h2>
          <ChartBox label="Distribution of delivery days" option={{ tooltip: {}, xAxis: { type: "category", data: data.delivery_days_distribution.map((d) => d.days) }, yAxis: { type: "value" }, series: [{ type: "bar", data: data.delivery_days_distribution.map((d) => d.orders) }] }} />
        </Card>
        <Card>
          <h2 className="mb-2 text-lg">Estimated versus actual</h2>
          <ChartBox label="Estimated and actual delivery days by month" option={{ tooltip: { trigger: "axis" }, legend: { data: ["Actual", "Estimated"] }, xAxis: { type: "category", data: data.estimated_vs_actual.map((m) => m.month) }, yAxis: { type: "value" }, series: [{ name: "Actual", type: "line", data: data.estimated_vs_actual.map((m) => m.actual_days) }, { name: "Estimated", type: "line", data: data.estimated_vs_actual.map((m) => m.estimated_days) }] }} />
        </Card>
        <Card>
          <h2 className="mb-2 text-lg">Late deliveries by state</h2>
          <ChartBox label="Late delivery rate by state" option={{ tooltip: {}, xAxis: { type: "category", data: data.late_rate_by_state.map((s) => s.state) }, yAxis: { type: "value", axisLabel: { formatter: "{value}" } }, series: [{ type: "bar", data: data.late_rate_by_state.map((s) => s.late_rate) }] }} />
        </Card>
      </div>
    </div>
  );
}

interface Sellers {
  top_sellers: { seller_id: string; seller_state: string | null; revenue: number; orders: number; avg_review: number | null; sparkline: number[] }[];
  seller_state_distribution: { state: string; sellers: number; revenue: number }[];
  review_score_distribution: { score: number; orders: number }[];
}

function SellersTab({ filters, range }: { filters: Filters; range: { start: string; end: string } }) {
  const query = useDashboard<Sellers>("sellers", filters, range);
  if (query.isPending) return <Loading />;
  if (query.isError) return <EmptyState title="Sellers could not be loaded">{query.error.message}</EmptyState>;
  const data = query.data;
  return (
    <div className="grid gap-6">
      <Card>
        <div className="mb-2 flex items-center justify-between"><h2 className="text-lg">Top sellers</h2><Button variant="secondary" onClick={() => downloadText("top-sellers.csv", toCsv(["seller_id", "seller_state", "revenue", "orders", "avg_review"], data.top_sellers.map((s) => [s.seller_id, s.seller_state, s.revenue, s.orders, s.avg_review])))}>CSV</Button></div>
        <table className="w-full text-left text-sm" aria-label="Top sellers"><thead><tr><th scope="col">Seller</th><th scope="col">State</th><th scope="col">Revenue</th><th scope="col">Orders</th><th scope="col">Trend</th></tr></thead>
          <tbody>{data.top_sellers.map((s) => <tr key={s.seller_id} className="border-t border-line"><td className="py-2">{s.seller_id}</td><td>{s.seller_state ?? "n/a"}</td><td>{formatMoney(s.revenue)}</td><td>{s.orders}</td><td className="w-32"><Sparkline values={s.sparkline} /></td></tr>)}</tbody></table>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-lg">Sellers by state</h2>
          <ChartBox label="Revenue by seller state" option={{ tooltip: {}, xAxis: { type: "category", data: data.seller_state_distribution.map((s) => s.state) }, yAxis: { type: "value" }, series: [{ type: "bar", data: data.seller_state_distribution.map((s) => s.revenue) }] }} />
        </Card>
        <Card>
          <h2 className="mb-2 text-lg">Review scores</h2>
          <ChartBox label="Distribution of review scores" option={{ tooltip: {}, xAxis: { type: "category", data: data.review_score_distribution.map((r) => String(r.score)) }, yAxis: { type: "value" }, series: [{ type: "bar", data: data.review_score_distribution.map((r) => r.orders) }] }} />
        </Card>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const meta = useQuery({ queryKey: ["catalog", "meta"], queryFn: () => apiJson<Meta>("/api/v1/catalog/meta"), staleTime: 300_000 });
  const [filters, setFilters] = useState<Filters>({ preset: "12m", state: "", category: "", compare: "none" });

  const range = useMemo(() => {
    const anchor = meta.data ? new Date(`${meta.data.data_as_of}T00:00:00`) : new Date();
    const preset = PRESETS.find((item) => item.id === filters.preset) ?? PRESETS[2];
    const end = addMonths(new Date(anchor.getFullYear(), anchor.getMonth(), 1), 1);
    const start = addMonths(end, -preset.months);
    return { start: iso(start), end: iso(end) };
  }, [meta.data, filters.preset]);

  const tabs = [
    { id: "overview", label: "Executive overview", content: <OverviewTab filters={filters} range={range} /> },
    { id: "sales", label: "Sales", content: <SalesTab filters={filters} range={range} /> },
    { id: "customers", label: "Customers", content: <CustomersTab filters={filters} range={range} /> },
    { id: "logistics", label: "Logistics", content: <LogisticsTab filters={filters} range={range} /> },
    { id: "sellers", label: "Sellers", content: <SellersTab filters={filters} range={range} /> },
  ];

  return (
    <div className="grid gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl">Dashboard</h1>
          <p className="text-sm text-ink-muted">Figures use the data your role can see. Periods end at {meta.data?.data_as_of ?? "the latest data"}.</p>
        </div>
      </header>

      <form className="grid gap-3 rounded-lg border border-line bg-panel p-4 sm:grid-cols-2 lg:grid-cols-5" aria-label="Dashboard filters" onSubmit={(event) => event.preventDefault()}>
        <div className="flex flex-col gap-1">
          <label htmlFor="preset" className="text-sm font-semibold">Period</label>
          <select id="preset" className="min-h-11 rounded-md border border-line bg-page px-3" value={filters.preset} onChange={(event) => setFilters({ ...filters, preset: event.target.value as Filters["preset"] })}>
            {PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="state" className="text-sm font-semibold">State</label>
          <input id="state" maxLength={2} placeholder="for example SP" className="min-h-11 rounded-md border border-line bg-page px-3 uppercase" value={filters.state} onChange={(event) => setFilters({ ...filters, state: event.target.value.toUpperCase() })} />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="category" className="text-sm font-semibold">Category</label>
          <input id="category" maxLength={60} placeholder="for example bed_bath_table" className="min-h-11 rounded-md border border-line bg-page px-3" value={filters.category} onChange={(event) => setFilters({ ...filters, category: event.target.value.toLowerCase() })} />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="compare" className="text-sm font-semibold">Compare with</label>
          <select id="compare" className="min-h-11 rounded-md border border-line bg-page px-3" value={filters.compare} onChange={(event) => setFilters({ ...filters, compare: event.target.value as Compare })}>
            <option value="none">Nothing</option>
            <option value="previous">Previous period</option>
            <option value="yoy">Same period last year</option>
          </select>
        </div>
      </form>

      <Tabs label="Dashboard sections" items={tabs} />
    </div>
  );
}
