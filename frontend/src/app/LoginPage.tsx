import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button, Input } from "../components/ui";
import { ApiError, login } from "../lib/http";

export const loginSchema = z.object({
  email: z.email("Enter a valid email address."),
  password: z.string().min(1, "Enter your password."),
});
type LoginForm = z.infer<typeof loginSchema>;

const DEMO_ACCOUNTS = [
  { label: "Executive", email: "executive@meridian.example" },
  { label: "Regional manager", email: "regional.manager@meridian.example" },
  { label: "Category manager", email: "category.manager@meridian.example" },
  { label: "Seller partner", email: "seller.partner@meridian.example" },
  { label: "Analyst", email: "analyst@meridian.example" },
  { label: "Admin", email: "admin@meridian.example" },
];
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/app/chat";
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema), defaultValues: { email: "", password: "" } });

  async function onSubmit(values: LoginForm) {
    setServerError(null);
    try {
      await login(values.email, values.password);
      navigate(from, { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) {
        setServerError("Too many attempts. Wait a few minutes and try again.");
      } else {
        // The server answers the same way for wrong passwords and locked accounts, so the message does too.
        setServerError("Invalid email or password. After five failed attempts the account is locked for 15 minutes.");
      }
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <aside className="hidden flex-col justify-between bg-brand p-12 text-on-brand lg:flex" aria-label="About the workspace">
        <Link to="/" className="text-lg font-bold text-on-brand no-underline">Meridian</Link>
        <div>
          <h1 className="text-4xl text-on-brand">Trusted answers from your data, in plain language</h1>
          <p className="mt-4 max-w-md opacity-90">Every answer respects your role and is recorded in the audit log.</p>
        </div>
        <p className="text-xs opacity-80">Demonstration with public historical data.</p>
      </aside>

      <main className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <h1 className="text-3xl">Sign in</h1>
          <p className="mt-2 text-ink-muted">Use your workspace account.</p>

          <form className="mt-8 grid gap-5" onSubmit={handleSubmit(onSubmit)} noValidate aria-describedby={serverError ? "login-error" : undefined}>
            <Input label="Email" type="email" autoComplete="username" error={errors.email?.message} {...register("email")} />
            <Input label="Password" type="password" autoComplete="current-password" error={errors.password?.message} {...register("password")} />
            {serverError ? (
              <p id="login-error" role="alert" className="rounded-md border border-line p-3 text-sm text-error">
                {serverError}
              </p>
            ) : null}
            <Button type="submit" variant="accent" disabled={isSubmitting}>
              {isSubmitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>

          {DEMO_MODE ? (
            <section className="mt-8" aria-labelledby="demo-title">
              <h2 id="demo-title" className="text-sm font-semibold">Demonstration accounts</h2>
              <p className="mt-1 text-xs text-ink-muted">Local demonstration only. Choose one to fill the form, then sign in.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {DEMO_ACCOUNTS.map((account) => (
                  <button
                    key={account.email}
                    type="button"
                    onClick={() => setValue("email", account.email, { shouldValidate: true })}
                    className="min-h-11 rounded-full border border-line px-3 text-xs font-semibold text-ink hover:bg-panel"
                  >
                    {account.label}
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          <p className="mt-8 text-sm">
            <Link to="/">Back to the website</Link>
          </p>
        </div>
      </main>
    </div>
  );
}
