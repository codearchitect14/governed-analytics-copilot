import clsx from "clsx";
import { useId, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type KeyboardEvent, type ReactNode, type TextareaHTMLAttributes } from "react";
import { Link } from "react-router-dom";

type Variant = "primary" | "accent" | "secondary" | "ghost";

const buttonVariants: Record<Variant, string> = {
  primary: "bg-brand text-on-brand hover:opacity-90",
  accent: "bg-action text-on-action hover:opacity-90",
  secondary: "border border-line bg-panel text-ink hover:bg-panel-strong",
  ghost: "text-ink hover:bg-panel",
};

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={clsx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold transition-opacity disabled:opacity-50",
        buttonVariants[variant],
        className,
      )}
      {...props}
    />
  );
}

export function LinkButton({
  to,
  variant = "primary",
  className,
  children,
}: {
  to: string;
  variant?: Variant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      className={clsx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold no-underline",
        buttonVariants[variant],
        className,
      )}
    >
      {children}
    </Link>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={clsx("rounded-lg border border-line bg-panel p-6 shadow-1", className)}>
      {children}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "error" }) {
  const tones = {
    neutral: "bg-panel-strong text-ink-muted",
    ok: "bg-panel-strong text-ok",
    warn: "bg-panel-strong text-warn",
    error: "bg-panel-strong text-error",
  };
  return (
    <span className={clsx("inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold", tones[tone])}>
      {children}
    </span>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  id,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  id: string;
}) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-semibold text-ink">
        {label}
      </label>
      {children}
      {hint ? (
        <p id={hintId} className="text-xs text-ink-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const inputClass =
  "min-h-11 w-full rounded-md border border-line bg-page px-3 py-2 text-base text-ink placeholder:text-ink-muted";

export function Input({ label, hint, error, id, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string; id?: string }) {
  const generated = useId();
  const fieldId = id ?? generated;
  return (
    <Field label={label} hint={hint} error={error} id={fieldId}>
      <input
        id={fieldId}
        className={inputClass}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hint ? `${fieldId}-hint` : null, error ? `${fieldId}-error` : null].filter(Boolean).join(" ") || undefined}
        {...props}
      />
    </Field>
  );
}

export function Textarea({ label, hint, error, id, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: string; error?: string; id?: string }) {
  const generated = useId();
  const fieldId = id ?? generated;
  return (
    <Field label={label} hint={hint} error={error} id={fieldId}>
      <textarea
        id={fieldId}
        className={clsx(inputClass, "min-h-32")}
        aria-invalid={error ? true : undefined}
        aria-describedby={[hint ? `${fieldId}-hint` : null, error ? `${fieldId}-error` : null].filter(Boolean).join(" ") || undefined}
        {...props}
      />
    </Field>
  );
}

export interface TabItem {
  id: string;
  label: string;
  content: ReactNode;
}

export function Tabs({ items, label }: { items: TabItem[]; label: string }) {
  const [active, setActive] = useState(items[0]?.id ?? "");
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const baseId = useId();

  function move(delta: number) {
    const index = items.findIndex((item) => item.id === active);
    const next = items[(index + delta + items.length) % items.length];
    setActive(next.id);
    refs.current[next.id]?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowRight") move(1);
    if (event.key === "ArrowLeft") move(-1);
    if (event.key === "Home") setActive(items[0].id);
    if (event.key === "End") setActive(items[items.length - 1].id);
  }

  return (
    <div>
      <div role="tablist" aria-label={label} className="flex flex-wrap gap-2 border-b border-line">
        {items.map((item) => {
          const selected = item.id === active;
          return (
            <button
              key={item.id}
              ref={(node) => {
                refs.current[item.id] = node;
              }}
              role="tab"
              id={`${baseId}-${item.id}-tab`}
              aria-selected={selected}
              aria-controls={`${baseId}-${item.id}-panel`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(item.id)}
              onKeyDown={onKeyDown}
              className={clsx(
                "min-h-11 border-b-2 px-4 py-2 text-sm font-semibold",
                selected ? "border-action text-ink" : "border-transparent text-ink-muted hover:text-ink",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {items.map((item) => (
        <div
          key={item.id}
          role="tabpanel"
          id={`${baseId}-${item.id}-panel`}
          aria-labelledby={`${baseId}-${item.id}-tab`}
          hidden={item.id !== active}
          className="pt-6"
        >
          {item.id === active ? item.content : null}
        </div>
      ))}
    </div>
  );
}

export function Disclosure({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group border-b border-line py-4">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 text-left font-semibold text-ink">
        {summary}
        <span aria-hidden="true" className="text-ink-muted transition-transform group-open:rotate-45">
          +
        </span>
      </summary>
      <div className="pt-2 text-ink-muted">{children}</div>
    </details>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={clsx("animate-pulse rounded-md bg-panel-strong", className)} />;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line p-8 text-center">
      <h3 className="text-lg">{title}</h3>
      {children ? <div className="mt-2 text-ink-muted">{children}</div> : null}
    </div>
  );
}

export function KpiCard({ label, value, delta, note }: { label: string; value: string; delta?: number | null; note?: string }) {
  const tone = delta === undefined || delta === null ? "text-ink-muted" : delta >= 0 ? "text-ok" : "text-error";
  const sign = delta !== undefined && delta !== null && delta > 0 ? "+" : "";
  return (
    <Card className="flex flex-col gap-2">
      <p className="text-sm text-ink-muted">{label}</p>
      <p className="text-3xl font-bold text-ink">{value}</p>
      {delta !== undefined && delta !== null ? (
        <p className={clsx("text-sm font-semibold", tone)}>
          {sign}
          {delta.toFixed(1)}% vs previous period
        </p>
      ) : null}
      {note ? <p className="text-xs text-ink-muted">{note}</p> : null}
    </Card>
  );
}

export function CodeBlock({ children, label }: { children: string; label: string }) {
  return (
    <pre aria-label={label} className="overflow-x-auto rounded-md border border-line bg-panel p-4 text-sm leading-relaxed text-ink">
      <code>{children}</code>
    </pre>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="text-sm text-ink-muted">
      <ol className="flex flex-wrap gap-2">
        {items.map((item, index) => (
          <li key={item.label} className="flex items-center gap-2">
            {index > 0 ? <span aria-hidden="true">/</span> : null}
            {item.to ? <Link to={item.to}>{item.label}</Link> : <span aria-current="page">{item.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function Section({ id, title, intro, children }: { id?: string; title?: string; intro?: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={id && title ? `${id}-title` : undefined} className="py-12 md:py-16">
      <div className="container-page">
        {title ? (
          <h2 id={id ? `${id}-title` : undefined} className="text-3xl">
            {title}
          </h2>
        ) : null}
        {intro ? <p className="mt-3 max-w-2xl text-lg text-ink-muted">{intro}</p> : null}
        <div className="mt-8">{children}</div>
      </div>
    </section>
  );
}
