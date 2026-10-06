/*
  Site copy. Every claim here must be true for the product as built. Where a result depends on a
  measurement that has not been made yet, the copy says so instead of showing a number.
*/

export const PRODUCT_NAME = "Meridian Data Copilot";

export const ANNOUNCEMENT =
  "Demonstration build. Data is the public Olist Brazilian E-Commerce dataset, not a real company.";

export const PILLARS = [
  {
    title: "Governed metrics",
    body: "Answers come from one reviewed set of metric definitions. Revenue means the same thing everywhere it appears.",
  },
  {
    title: "Role based access",
    body: "Each role sees only its own rows and columns. Row filters are applied in the query and again in the database.",
  },
  {
    title: "Auditable by design",
    body: "Every question, plan, SQL statement and denial is written to a hash chained log that can be verified.",
  },
] as const;

export const HOW_IT_WORKS = [
  { title: "Ask", body: "Type a question in plain language." },
  { title: "Resolve", body: "Known metric names and periods are matched locally, with no model call." },
  { title: "Plan", body: "When needed, a model proposes a plan over governed metrics only." },
  { title: "Validate", body: "The SQL is checked: one read only statement over allowed tables." },
  { title: "Apply policy", body: "Row filters and masks are added for your role before anything runs." },
  { title: "Answer and audit", body: "You get the figures, a chart, the SQL and a record of what happened." },
] as const;

export const ROLE_USE_CASES = [
  {
    role: "Executive",
    question: "Revenue by month for the last 12 months",
    answer: "A line chart of monthly revenue, with the figure for each month and the change from the month before.",
  },
  {
    role: "Regional manager",
    question: "Revenue by customer state",
    answer: "Only the states in your region list appear. Other states are not returned at all.",
  },
  {
    role: "Category manager",
    question: "Revenue by product category",
    answer: "Only the categories assigned to you are shown. Order level data is not available to this role.",
  },
  {
    role: "Seller partner",
    question: "Items sold by seller state",
    answer: "Only your own seller account is included in the result.",
  },
  {
    role: "Analyst",
    question: "Unique customers by month",
    answer: "Customer identifiers are masked. Free form SQL questions are allowed and always audited.",
  },
] as const;

export const SECURITY_LAYERS = [
  { title: "Route checks", body: "Each endpoint checks the user's role before doing any work." },
  { title: "Policy engine", body: "The role's allowed tables, row filters and masked columns are computed for every request." },
  { title: "SQL validation", body: "Only a single read statement over allowed tables gets through. Functions that read files or sleep are blocked." },
  { title: "Database row level security", body: "The database itself hides rows outside the user's scope, even if a higher layer had a defect." },
  { title: "Audit log", body: "A hash chained record of every request. Changes to past rows break the chain and are detected." },
] as const;

export const FAQ = [
  {
    q: "Does the model see my data?",
    a: "The model receives the question, the names of metrics and columns, and a few example questions. Result rows are never sent to a model, except in an optional narrative that uses aggregated figures.",
  },
  {
    q: "Can the assistant run any SQL?",
    a: "No. Generated SQL is parsed and must be one read only SELECT over allowed analytics tables. Anything else is rejected and recorded.",
  },
  {
    q: "What happens when a question is denied?",
    a: "You see a plain explanation of the reason. The attempt is written to the audit log with the same detail.",
  },
  {
    q: "Are the answers always right?",
    a: "No system is. Every answer shows the SQL and the metric definitions it used, so it can be checked. Accuracy figures will be published once the evaluation harness is run.",
  },
  {
    q: "Which data is used?",
    a: "The public Olist Brazilian E-Commerce dataset, covering 2016 to 2018. It is licensed for non commercial use and is attributed on the Data attribution page.",
  },
  {
    q: "Which models are used?",
    a: "Groq (openai/gpt-oss-20b) first, with Google Gemini as the fallback. Both are on free tiers. A local embedding model handles question matching.",
  },
  {
    q: "Can I self host it?",
    a: "Yes. Docker Compose starts the database, API, web app and orchestration. The README describes the steps.",
  },
  {
    q: "Is it compliant with a specific standard?",
    a: "No compliance certification is claimed. The Security page lists what is implemented and what is not.",
  },
  {
    q: "Is any of this live data?",
    a: "No. This is a demonstration with historical public data. Dashboards show 2016 to 2018.",
  },
  {
    q: "How do I get access?",
    a: "The demonstration accounts are listed in the README. Requests for a walkthrough can be sent through the contact form.",
  },
] as const;

export const METRICS_CATALOG = [
  { name: "Revenue", definition: "Item prices on orders that are not canceled. Currency BRL.", synonyms: "sales, turnover" },
  { name: "GMV", definition: "Item prices plus freight on orders that are not canceled.", synonyms: "gross merchandise value" },
  { name: "Orders", definition: "Distinct orders that are not canceled.", synonyms: "order count, purchases" },
  { name: "Items sold", definition: "Order items on orders that are not canceled.", synonyms: "units, quantity sold" },
  { name: "Average order value", definition: "Revenue divided by orders.", synonyms: "AOV, basket size" },
  { name: "Unique customers", definition: "Distinct real customers with at least one order.", synonyms: "customers, buyers" },
  { name: "Payment value", definition: "Total paid on orders that are not canceled.", synonyms: "payments" },
  { name: "Cancellation rate", definition: "Canceled orders divided by all orders.", synonyms: "cancel rate" },
  { name: "On time delivery rate", definition: "Delivered orders that arrived on or before the estimated date.", synonyms: "punctuality" },
  { name: "Average delivery days", definition: "Days from purchase to delivery, delivered orders only.", synonyms: "lead time" },
  { name: "Average review score", definition: "Average review score (1 to 5) of the latest review per order.", synonyms: "rating, satisfaction" },
  { name: "Repeat customer rate", definition: "Share of orders from customers who had ordered before.", synonyms: "retention rate" },
] as const;

export const CONTACT_TOPICS = ["Request a walkthrough", "Technical question", "Partnership", "Other"] as const;
