import { LinkButton, Section } from "../../components/ui";

export function NotFound() {
  return (
    <Section>
      <p className="text-sm font-semibold text-action">404</p>
      <h1 className="mt-2 text-4xl">This page could not be found</h1>
      <p className="mt-4 max-w-xl text-ink-muted">The address may be mistyped or the page may have moved.</p>
      <div className="mt-8">
        <LinkButton to="/">Back to the home page</LinkButton>
      </div>
    </Section>
  );
}

export function ServerError() {
  return (
    <Section>
      <h1 className="text-4xl">Something went wrong</h1>
      <p className="mt-4 max-w-xl text-ink-muted">The page could not be shown. Try again in a moment.</p>
      <div className="mt-8">
        <LinkButton to="/">Back to the home page</LinkButton>
      </div>
    </Section>
  );
}

/** Placeholder for the sign in route. The application itself is built in the next phase. */
export function AppPlaceholder() {
  return (
    <Section>
      <h1 className="text-4xl">Workspace sign in</h1>
      <p className="mt-4 max-w-xl text-ink-muted">
        The workspace is built in the application phase. Until then, the demonstration accounts can be used through the API documentation.
      </p>
      <div className="mt-8">
        <LinkButton to="/contact" variant="secondary">Request a walkthrough</LinkButton>
      </div>
    </Section>
  );
}
