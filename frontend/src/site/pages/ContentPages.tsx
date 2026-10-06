import { Breadcrumbs, Card, LinkButton, Section } from "../../components/ui";
import { METRICS_CATALOG, ROLE_USE_CASES, SECURITY_LAYERS } from "../../lib/content";

function PageHeader({ title, intro, crumbs }: { title: string; intro: string; crumbs: string }) {
  return (
    <section className="py-10 md:py-14">
      <div className="container-page">
        <Breadcrumbs items={[{ label: "Home", to: "/" }, { label: crumbs }]} />
        <h1 className="mt-4 text-4xl">{title}</h1>
        <p className="mt-4 max-w-2xl text-lg text-ink-muted">{intro}</p>
      </div>
    </section>
  );
}

const ARCHITECTURE = `Browser (React)
   |  HTTPS, session cookie, bearer token
   v
API (FastAPI)  --  route checks, policy engine, audit writer
   |                    |
   |  guarded SQL       |  hash chained audit log (PostgreSQL)
   v                    v
Warehouse (PostgreSQL) -- dbt marts, MetricFlow semantic layer, row level security
   ^
   |  plans from the semantic layer; LLM plans validated before use
LLM providers (Groq, Google Gemini, free tiers)`;

export function Platform() {
  return (
    <>
      <PageHeader title="Platform" intro="How the pieces fit together: a governed semantic layer, a guarded query path and an audit trail." crumbs="Platform" />
      <Section id="architecture" title="Architecture" intro="A single request path, from question to audited answer.">
        <pre aria-label="Architecture overview" className="overflow-x-auto rounded-md border border-line bg-panel p-4 text-sm">
          <code>{ARCHITECTURE}</code>
        </pre>
      </Section>
      <Section id="how-it-works" title="The request flow" intro="Each step stops the flow as soon as it has an answer.">
        <ol className="list-decimal space-y-2 pl-6 text-ink-muted">
          <li>Cache: an identical question for the same policy returns the stored plan.</li>
          <li>Semantic cache: a close match to an earlier question reuses its plan.</li>
          <li>Rule resolver: known metric names and periods are resolved locally.</li>
          <li>Language model plan: only when needed, over the governed catalog.</li>
          <li>SQL fallback: only for roles whose policy allows it, and only over allowed tables.</li>
          <li>Validation, policy rewrite, cost check, execution and audit.</li>
        </ol>
      </Section>
      <Section id="semantic-layer" title="The semantic layer" intro="Metrics are defined once and reused everywhere. Each has a description and synonyms.">
        <p className="max-w-2xl text-ink-muted">
          Definitions live in version controlled files. The validator checks them against the warehouse before a release. To add a metric, a developer adds a definition and a test; the catalog index then picks it up.
        </p>
      </Section>
      <Section id="metrics" title="Metric catalog" intro="The metrics available in this build, with their plain language definitions.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-left text-sm">
            <caption className="sr-only">Metrics and their definitions</caption>
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="py-2 pr-4">Metric</th>
                <th scope="col" className="py-2 pr-4">Definition</th>
                <th scope="col" className="py-2">Also called</th>
              </tr>
            </thead>
            <tbody>
              {METRICS_CATALOG.map((metric) => (
                <tr key={metric.name} className="border-b border-line align-top">
                  <th scope="row" className="py-3 pr-4 font-semibold">{metric.name}</th>
                  <td className="py-3 pr-4 text-ink-muted">{metric.definition}</td>
                  <td className="py-3 text-ink-muted">{metric.synonyms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}

export function Solutions() {
  return (
    <>
      <PageHeader title="Solutions" intro="One workspace, with access shaped to each role. Scenarios use the sample questions the product is tested with." crumbs="Solutions" />
      <Section>
        <div className="grid gap-6 md:grid-cols-2">
          {ROLE_USE_CASES.map((item) => (
            <Card key={item.role}>
              <h2 className="text-xl">{item.role}</h2>
              <p className="mt-3 text-sm font-semibold">Example question</p>
              <p className="text-ink-muted">“{item.question}”</p>
              <p className="mt-3 text-sm font-semibold">What the answer looks like</p>
              <p className="text-ink-muted">{item.answer}</p>
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}

export function Security() {
  return (
    <>
      <PageHeader title="Security" intro="What is implemented, how it is checked, and what is not claimed." crumbs="Security" />
      <Section id="layers" title="Authorization layers">
        <ol className="grid gap-4 md:grid-cols-2">
          {SECURITY_LAYERS.map((layer) => (
            <li key={layer.title}>
              <Card>
                <h2 className="text-lg">{layer.title}</h2>
                <p className="mt-2 text-ink-muted">{layer.body}</p>
              </Card>
            </li>
          ))}
        </ol>
      </Section>
      <Section id="authentication" title="Authentication and sessions">
        <ul className="list-disc space-y-2 pl-6 text-ink-muted">
          <li>Passwords are hashed with Argon2id. Accounts lock for 15 minutes after five failed attempts.</li>
          <li>Access tokens last 15 minutes. Refresh tokens rotate and are stored in an httpOnly cookie. Keeping access tokens out of browser storage is part of the application build.</li>
          <li>Reuse of a rotated refresh token revokes the whole session family.</li>
        </ul>
      </Section>
      <Section id="data-handling" title="Data handling">
        <ul className="list-disc space-y-2 pl-6 text-ink-muted">
          <li>Customer identifiers are masked for the analyst role. Masking is by hash, so values stay linkable across queries.</li>
          <li>Result rows are not sent to a language model.</li>
          <li>Audit records are kept in an append only log with a verifiable hash chain.</li>
        </ul>
      </Section>
      <Section id="scope" title="Scope and limits" intro="Stated plainly, so that nobody relies on a claim this build does not make.">
        <ul className="list-disc space-y-2 pl-6 text-ink-muted">
          <li>No compliance certification (such as SOC 2, ISO 27001 or GDPR attestation) is claimed.</li>
          <li>No external penetration test has been commissioned. Internal tests cover the SQL guard and the permission matrix.</li>
          <li>The dataset is public and historical. It is not production personal data.</li>
          <li>Backup and restore procedures are planned for the release phase and are not yet documented as tested.</li>
        </ul>
      </Section>
    </>
  );
}

export function Benchmarks() {
  return (
    <>
      <PageHeader title="Benchmarks" intro="How results will be measured and reported. Figures appear only after a measured run." crumbs="Benchmarks" />
      <Section id="status" title="Status">
        <Card>
          <p className="text-ink-muted">
            No benchmark results are published yet. The results table will be generated from the evaluation harness, with the model, the prompt version,
            the sample size and the run date for each figure. Nothing on this page is an estimate.
          </p>
        </Card>
      </Section>
      <Section id="methodology" title="Methodology">
        <ul className="list-disc space-y-2 pl-6 text-ink-muted">
          <li>Olist golden set: 150 hand verified questions. Execution accuracy compares result sets with gold SQL.</li>
          <li>Permission and adversarial set: each case must return no rows outside the role's scope.</li>
          <li>BIRD Mini-Dev and Spider dev: raw text to SQL on the fallback path, without the semantic layer. Reported separately and labelled as such.</li>
        </ul>
      </Section>
    </>
  );
}

export function Resources() {
  return (
    <>
      <PageHeader title="Resources" intro="Documentation, the API reference and the source." crumbs="Resources" />
      <Section>
        <div className="grid gap-6 md:grid-cols-3">
          <Card>
            <h2 className="text-lg">Documentation</h2>
            <p className="mt-2 text-ink-muted">Architecture, the semantic layer guide, evaluation and the security model are kept in the repository docs folder.</p>
          </Card>
          <Card>
            <h2 className="text-lg">API reference</h2>
            <p className="mt-2 text-ink-muted">The interactive OpenAPI reference is served by the API at /docs when it runs locally.</p>
            <p className="mt-3"><a href="/docs">Open the API reference</a></p>
          </Card>
          <Card>
            <h2 className="text-lg">Data dictionary</h2>
            <p className="mt-2 text-ink-muted">Each mart and metric is described in the dbt documentation generated by the build.</p>
          </Card>
        </div>
      </Section>
    </>
  );
}

export function About() {
  return (
    <>
      <PageHeader title="About" intro="A demonstration analytics product built to show governed, auditable answers from business data." crumbs="About" />
      <Section>
        <p className="max-w-2xl text-ink-muted">
          Meridian Data Copilot is a project to show how natural language analytics can respect roles, stay auditable and keep model use small.
          The name and the company are fictional. The data is a public dataset.
        </p>
        <div className="mt-8">
          <LinkButton to="/contact" variant="accent">Get in touch</LinkButton>
        </div>
      </Section>
    </>
  );
}
