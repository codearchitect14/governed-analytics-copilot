import type { ReactNode } from "react";
import { Breadcrumbs, Section } from "../../components/ui";

const DEMO_NOTE =
  "Demonstration document. This text describes a demonstration build and is not a legal agreement. It has not been reviewed by a lawyer.";

function LegalPage({ title, slug, children }: { title: string; slug: string; children: ReactNode }) {
  return (
    <>
      <section className="py-10 md:py-14">
        <div className="container-page">
          <Breadcrumbs items={[{ label: "Home", to: "/" }, { label: "Legal" }, { label: title }]} />
          <h1 className="mt-4 text-4xl">{title}</h1>
          <p className="mt-4 rounded-md border border-line bg-panel p-4 text-sm text-ink-muted" data-document={slug}>
            {DEMO_NOTE}
          </p>
        </div>
      </section>
      <Section>
        <div className="max-w-3xl space-y-4 text-ink-muted">{children}</div>
      </Section>
    </>
  );
}

export function Privacy() {
  return (
    <LegalPage title="Privacy notice" slug="privacy">
      <p>The contact form stores your name, email address, company, topic and message so that someone can reply. Nothing else is stored from the form.</p>
      <p>The demonstration data is public and historical. The application writes an audit record for each question asked by a signed in user.</p>
      <p>Requests to remove a contact record can be sent through the contact form.</p>
    </LegalPage>
  );
}

export function Terms() {
  return (
    <LegalPage title="Terms of use" slug="terms">
      <p>The demonstration may be used to evaluate the product. Do not enter personal data into it.</p>
      <p>The service is provided as it is, without warranty, and may change or stop at any time.</p>
    </LegalPage>
  );
}

export function Cookies() {
  return (
    <LegalPage title="Cookie notice" slug="cookies">
      <p>The website stores your theme choice in your browser. It does not use advertising or analytics cookies.</p>
      <p>The workspace sets an httpOnly refresh cookie when you sign in. The cookie is used only to keep your session.</p>
    </LegalPage>
  );
}

export function Accessibility() {
  return (
    <LegalPage title="Accessibility statement" slug="accessibility">
      <p>The site is designed to meet WCAG 2.2 Level AA. It supports keyboard navigation, visible focus, reduced motion and light and dark themes.</p>
      <p>No formal audit has been completed yet. Report problems through the contact form and include the page address.</p>
    </LegalPage>
  );
}

export function Attribution() {
  return (
    <LegalPage title="Data attribution" slug="attribution">
      <p>
        Business data: Olist Brazilian E-Commerce public dataset, published on Kaggle as olistbr/brazilian-ecommerce. Licence: CC BY-NC-SA 4.0,
        which permits non commercial use with attribution and share alike terms.
      </p>
      <p>Benchmark datasets (BIRD Mini-Dev, Spider) are listed here when they are added in the evaluation phase.</p>
      <p>Icons are provided by Lucide under the ISC licence. Typefaces are Inter and IBM Plex Mono, licensed under the SIL Open Font License.</p>
    </LegalPage>
  );
}
