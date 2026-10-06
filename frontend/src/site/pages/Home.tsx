import { Card, Disclosure, LinkButton, Section } from "../../components/ui";
import { Tabs } from "../../components/ui";
import { CodeBlock } from "../../components/ui";
import { FAQ, HOW_IT_WORKS, PILLARS, ROLE_USE_CASES, SECURITY_LAYERS } from "../../lib/content";

const STACK = ["PostgreSQL", "dbt", "MetricFlow", "FastAPI", "Dagster", "React"];

const EXAMPLE_SQL = `SELECT customer_state, SUM(line_revenue) AS revenue
FROM (
  SELECT customer_state, line_revenue
  FROM analytics.fct_order_items
  WHERE customer_state IN ('SP', 'RJ')   -- row filter for this role
) AS fct_order_items
GROUP BY customer_state
LIMIT 1000;`;

function ChatMock() {
  return (
    <div aria-label="Illustrative interface: a question, a chart and its SQL" role="img" className="rounded-lg border border-line bg-panel p-4 shadow-2">
      <div className="ml-auto max-w-[80%] rounded-md bg-brand p-3 text-sm text-on-brand">Revenue by customer state</div>
      <div className="mt-3 rounded-md border border-line bg-page p-3">
        <p className="text-xs text-ink-muted">Illustrative example</p>
        <div className="mt-2 flex h-32 items-end gap-3" aria-hidden="true">
          {[72, 48, 90, 35, 60].map((height, index) => (
            <div key={index} className="flex-1 rounded-t-sm bg-action" style={{ height: `${height}%` }} />
          ))}
        </div>
      </div>
      <p className="mt-3 text-xs text-ink-muted">Governed metric: revenue · Route: rule · Audit id: 1042</p>
    </div>
  );
}

export default function Home() {
  return (
    <>
      <section className="py-12 md:py-20" aria-labelledby="hero-title">
        <div className="container-page grid items-center gap-10 lg:grid-cols-2">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-action">Governed analytics</p>
            <h1 id="hero-title" className="mt-3 text-4xl md:text-5xl">
              Trusted answers from your data, in plain language
            </h1>
            <p className="mt-4 max-w-xl text-lg text-ink-muted">
              Ask business questions against governed metrics. Access follows each role, and every answer is written to an audit log you can verify.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <LinkButton to="/app/login" variant="accent">Sign in to the workspace</LinkButton>
              <LinkButton to="/platform#how-it-works" variant="secondary">Watch product tour</LinkButton>
            </div>
            <p className="mt-4 text-xs text-ink-muted">Demonstration with public historical data. The product tour is a written walkthrough.</p>
          </div>
          <ChatMock />
        </div>
      </section>

      <section aria-label="Built on open standards" className="border-y border-line bg-panel py-6">
        <div className="container-page flex flex-wrap items-center justify-center gap-x-8 gap-y-3">
          <p className="text-sm font-semibold text-ink-muted">Built on open standards</p>
          <ul className="flex flex-wrap gap-x-6 gap-y-2 text-sm font-semibold text-ink-muted">
            {STACK.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </div>
      </section>

      <Section id="pillars" title="Why teams trust it" intro="Three properties that matter most for shared analytics.">
        <div className="grid gap-6 md:grid-cols-3">
          {PILLARS.map((pillar) => (
            <Card key={pillar.title}>
              <h3 className="text-xl">{pillar.title}</h3>
              <p className="mt-2 text-ink-muted">{pillar.body}</p>
            </Card>
          ))}
        </div>
      </Section>

      <Section id="how-it-works" title="How it works" intro="Each question moves through the same steps. Most are resolved without any model call.">
        <ol className="grid gap-4 md:grid-cols-3 lg:grid-cols-6">
          {HOW_IT_WORKS.map((step, index) => (
            <li key={step.title} className="rounded-lg border border-line bg-page p-4">
              <p className="text-sm font-bold text-action">Step {index + 1}</p>
              <h3 className="mt-1 text-lg">{step.title}</h3>
              <p className="mt-2 text-sm text-ink-muted">{step.body}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section id="showcase" title="See the whole answer" intro="Each answer comes with its chart, its SQL, its explanation and its audit record.">
        <Tabs
          label="Product showcase"
          items={[
            {
              id: "ask",
              label: "Ask",
              content: <p className="max-w-2xl text-ink-muted">Type a question in plain language. Suggested questions match your role, and clarification questions appear when a period or metric is unclear.</p>,
            },
            {
              id: "sql",
              label: "Inspect SQL",
              content: (
                <div className="grid gap-4">
                  <p className="max-w-2xl text-ink-muted">The final SQL includes the row filter that was added for your role. The generated version is kept for comparison.</p>
                  <CodeBlock label="Example SQL after policy">{EXAMPLE_SQL}</CodeBlock>
                </div>
              ),
            },
            {
              id: "visualize",
              label: "Visualize",
              content: <p className="max-w-2xl text-ink-muted">Charts are chosen from the shape of the result: a line for a time series, bars for a ranking, a card for one number.</p>,
            },
            {
              id: "audit",
              label: "Audit",
              content: <p className="max-w-2xl text-ink-muted">Administrators can see who asked what, which route answered, what was denied and why, and verify that the log has not been edited.</p>,
            },
          ]}
        />
      </Section>

      <section aria-labelledby="metrics-title" className="bg-brand py-12 text-on-brand">
        <div className="container-page">
          <h2 id="metrics-title" className="text-3xl text-on-brand">Measured results</h2>
          <p className="mt-3 max-w-2xl">
            Accuracy, the share of questions answered without a model call, tokens per question and permission leakage will be shown here
            from the evaluation harness. They are not shown until that harness has run, so no figure appears here before it has been measured.
          </p>
          <ul className="mt-6 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {["Execution accuracy", "Answered without a model call", "Average tokens per question", "Permission leakage rate"].map((label) => (
              <li key={label} className="rounded-md border border-white/30 p-4">
                <p className="font-semibold">{label}</p>
                <p className="mt-1 opacity-80">Available after the Phase 10 evaluation run</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <Section id="use-cases" title="Built for each role" intro="Every role sees the same governed metrics, with its own rows and columns.">
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {ROLE_USE_CASES.map((item) => (
            <Card key={item.role}>
              <h3 className="text-lg">{item.role}</h3>
              <p className="mt-3 text-sm font-semibold text-ink">“{item.question}”</p>
              <p className="mt-2 text-sm text-ink-muted">{item.answer}</p>
            </Card>
          ))}
        </div>
      </Section>

      <Section id="security" title="Security and governance" intro="Five layers stand between a question and the data. Each one works without the others.">
        <ol className="grid gap-4 md:grid-cols-5">
          {SECURITY_LAYERS.map((layer, index) => (
            <li key={layer.title} className="rounded-lg border border-line p-4">
              <p className="text-sm font-bold text-action">Layer {index + 1}</p>
              <h3 className="mt-1 text-base">{layer.title}</h3>
              <p className="mt-2 text-sm text-ink-muted">{layer.body}</p>
            </li>
          ))}
        </ol>
        <p className="mt-6 text-sm">
          <LinkButton to="/security" variant="secondary">Read the security scope</LinkButton>
        </p>
      </Section>

      <Section id="dashboards" title="Dashboards on the same rules" intro="Business dashboards use the same policy engine, so each role sees only its own slice.">
        <div className="rounded-lg border border-line bg-panel p-6" role="img" aria-label="Illustrative dashboard: KPI cards and a revenue trend">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {["Revenue", "Orders", "Average order value", "Unique customers"].map((label) => (
              <div key={label} className="rounded-md bg-page p-3">
                <p className="text-xs text-ink-muted">{label}</p>
                <div className="mt-2 h-6 w-20 rounded bg-panel-strong" aria-hidden="true" />
              </div>
            ))}
          </div>
          <div className="mt-4 h-40 rounded-md bg-page p-3" aria-hidden="true">
            <div className="flex h-full items-end gap-2">
              {[40, 55, 48, 66, 72, 70, 84, 90].map((height, index) => (
                <div key={index} className="flex-1 rounded-t-sm bg-accent" style={{ height: `${height}%` }} />
              ))}
            </div>
          </div>
        </div>
        <p className="mt-4 text-xs text-ink-muted">Illustrative layout. The live dashboard is available after sign in.</p>
      </Section>

      <Section id="faq" title="Frequently asked questions">
        <div className="max-w-3xl">
          {FAQ.map((item) => (
            <Disclosure key={item.q} summary={item.q}>
              {item.a}
            </Disclosure>
          ))}
        </div>
      </Section>

      <section aria-labelledby="cta-title" className="border-t border-line bg-panel py-12">
        <div className="container-page flex flex-col items-start justify-between gap-6 md:flex-row md:items-center">
          <div>
            <h2 id="cta-title" className="text-3xl">Ready to look at the workspace?</h2>
            <p className="mt-2 text-ink-muted">Sign in with a demonstration account, or ask for a walkthrough.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <LinkButton to="/app/login" variant="accent">Sign in to the workspace</LinkButton>
            <LinkButton to="/contact" variant="secondary">Request a demo</LinkButton>
          </div>
        </div>
      </section>
    </>
  );
}
