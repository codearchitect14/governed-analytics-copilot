import type { ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, beforeEach, vi } from "vitest";
import { Button, Disclosure, Tabs } from "../components/ui";
import { contactSchema } from "./pages/Contact";
import { nextTheme, applyTheme } from "../lib/theme";
import Home from "./pages/Home";
import SiteLayout from "./SiteLayout";
import { NotFound } from "./pages/Status";
import { FAQ, ROLE_USE_CASES } from "../lib/content";

function renderAt(path: string, element: ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<SiteLayout />}>
          <Route path="/" element={<Home />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
      {element}
    </MemoryRouter>,
  );
}

describe("design system components", () => {
  it("renders a button with an accessible name and calls its handler", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);

    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("moves between tabs with the arrow keys and shows one panel at a time", async () => {
    render(
      <Tabs
        label="Sample"
        items={[
          { id: "one", label: "One", content: <p>First panel</p> },
          { id: "two", label: "Two", content: <p>Second panel</p> },
        ]}
      />,
    );
    const first = screen.getByRole("tab", { name: "One" });
    first.focus();

    await userEvent.keyboard("{ArrowRight}");

    expect(screen.getByRole("tab", { name: "Two" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Second panel")).toBeVisible();
  });

  it("opens an accordion answer from its summary", async () => {
    render(<Disclosure summary="Question?">Answer text</Disclosure>);

    await userEvent.click(screen.getByText("Question?"));

    expect(screen.getByText("Answer text").closest("details")).toHaveAttribute("open");
  });
});

describe("contact validation", () => {
  const valid = {
    name: "Ada",
    email: "ada@example.com",
    topic: "Request a walkthrough",
    message: "Could we see the workspace?",
    consent: true,
  };

  it("accepts a complete request", () => {
    expect(contactSchema.safeParse(valid).success).toBe(true);
  });

  it("rejects a bad email, a short message and a missing consent", () => {
    const result = contactSchema.safeParse({ ...valid, email: "not-an-email", message: "hi", consent: false });

    expect(result.success).toBe(false);
    const paths = result.success ? [] : result.error.issues.map((issue) => issue.path[0]);
    expect(paths).toEqual(expect.arrayContaining(["email", "message", "consent"]));
  });

  it("rejects an unknown topic", () => {
    expect(contactSchema.safeParse({ ...valid, topic: "Pricing war" }).success).toBe(false);
  });
});

describe("theme choice", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("cycles system, light and dark", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });

  it("sets and clears the data-theme attribute", () => {
    applyTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    applyTheme("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("still works when storage is blocked", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      renderAt("/", null);
      expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    } finally {
      spy.mockRestore();
    }
  });
});

describe("site pages", () => {
  it("shows the home headline, the sign in call to action and the skip link", () => {
    renderAt("/", null);

    expect(screen.getByRole("heading", { level: 1, name: "Trusted answers from your data, in plain language" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Sign in to the workspace" })[0]).toHaveAttribute("href", "/app/login");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });

  it("lists the five roles with example questions", () => {
    renderAt("/", null);

    for (const item of ROLE_USE_CASES) {
      expect(screen.getByText(`“${item.question}”`)).toBeInTheDocument();
    }
  });

  it("renders every FAQ entry", () => {
    renderAt("/", null);

    expect(FAQ.length).toBeGreaterThanOrEqual(8);
    for (const item of FAQ) {
      expect(screen.getByText(item.q)).toBeInTheDocument();
    }
  });

  it("does not show benchmark figures before they are measured", () => {
    renderAt("/", null);

    const band = screen.getByRole("heading", { name: "Measured results" }).closest("section");
    expect(within(band as HTMLElement).queryByText(/%/)).toBeNull();
  });

  it("shows the not found page for an unknown address", () => {
    render(
      <MemoryRouter initialEntries={["/does-not-exist"]}>
        <Routes>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "This page could not be found" })).toBeInTheDocument();
  });

  it("marks the navigation landmark and the current page", () => {
    renderAt("/", null);

    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});
