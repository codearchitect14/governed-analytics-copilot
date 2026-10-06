import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth, type SessionUser } from "../lib/auth-store";
import { parseSseBuffer, csvCell, toCsv, sortRows } from "../lib/util";
import { apiFetch, login, refreshSession } from "../lib/http";
import { streamQuestion } from "../lib/chat";
import { contactSchema } from "../site/pages/Contact";
import { RequireAdmin, RequireAuth } from "./guards";
import { loginSchema } from "./LoginPage";
import AppShell from "./AppShell";

const analyst: SessionUser = { id: "1", email: "analyst@meridian.example", full_name: "Analyst", role: "analyst", policy_version: 1 };
const admin: SessionUser = { ...analyst, id: "2", email: "admin@meridian.example", full_name: "Admin", role: "admin" };
const future = new Date(Date.now() + 15 * 60_000).toISOString();

function setUser(user: SessionUser | null) {
  if (user) useAuth.getState().setSession(user, "token-in-memory", future);
  else useAuth.getState().clear();
}

beforeEach(() => {
  window.localStorage.clear();
  setUser(null);
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("server sent events", () => {
  it("parses complete events and keeps the unfinished tail", () => {
    const chunk = 'event: step\ndata: {"state":"resolving","elapsed_ms":3}\n\nevent: result\ndata: {"route":"rule"}\n\nevent: st';
    const { events, rest } = parseSseBuffer(chunk);

    expect(events.map((e) => e.event)).toEqual(["step", "result"]);
    expect(events[0].data).toEqual({ state: "resolving", elapsed_ms: 3 });
    expect(rest).toBe("event: st");
  });

  it("skips malformed data without stopping the stream", () => {
    const { events } = parseSseBuffer('event: step\ndata: {broken\n\nevent: step\ndata: {"state":"done"}\n\n');

    expect(events).toHaveLength(1);
  });
});

describe("csv export", () => {
  it("neutralises cells that a spreadsheet could run as formulas", () => {
    expect(csvCell("=1+1")).toBe("'=1+1");
    expect(csvCell("+1")).toBe("'+1");
    expect(csvCell("plain")).toBe("plain");
  });

  it("quotes commas and newlines", () => {
    expect(toCsv(["a", "b"], [["x,y", "line\nbreak"]])).toBe('a,b\r\n"x,y","line\nbreak"');
  });
});

describe("table sorting", () => {
  it("sorts numbers numerically and keeps nulls last", () => {
    const rows: unknown[][] = [
      ["b", 10],
      ["a", null],
      ["c", 2],
    ];

    const sorted = sortRows(rows, ["name", "value"], { column: "value", direction: "asc" });

    expect(sorted.map((r) => r[0])).toEqual(["c", "b", "a"]);
  });
});

describe("forms", () => {
  it("requires a valid email and a password for sign in", () => {
    expect(loginSchema.safeParse({ email: "nope", password: "" }).success).toBe(false);
    expect(loginSchema.safeParse({ email: "ok@example.com", password: "x" }).success).toBe(true);
  });

  it("keeps the public contact rules", () => {
    expect(contactSchema.safeParse({ name: "A", email: "a@b.co", topic: "Other", message: "long enough text", consent: true }).success).toBe(false);
  });
});

describe("route guards", () => {
  it("sends an anonymous visitor to sign in", async () => {
    useAuth.setState({ status: "anonymous" });
    render(
      <MemoryRouter initialEntries={["/app/chat"]}>
        <Routes>
          <Route path="/app/login" element={<p>Sign in page</p>} />
          <Route
            path="/app/chat"
            element={
              <RequireAuth>
                <p>Chat</p>
              </RequireAuth>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Sign in page")).toBeInTheDocument();
  });

  it("shows a loading state while the session is being restored", () => {
    useAuth.setState({ status: "loading" });
    render(
      <MemoryRouter>
        <RequireAuth>
          <p>Chat</p>
        </RequireAuth>
      </MemoryRouter>,
    );

    expect(screen.getByLabelText("Checking your session")).toBeInTheDocument();
    expect(screen.queryByText("Chat")).toBeNull();
  });

  it("keeps non administrators out of admin pages", async () => {
    setUser(analyst);
    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <Routes>
          <Route path="/app/chat" element={<p>Back in chat</p>} />
          <Route
            path="/admin"
            element={
              <RequireAdmin>
                <p>Audit</p>
              </RequireAdmin>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Back in chat")).toBeInTheDocument();
  });
});

describe("navigation by role", () => {
  it("shows the administration group only to administrators", () => {
    setUser(analyst);
    const { unmount } = render(
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>,
    );
    expect(screen.queryByText("Users and roles")).toBeNull();
    unmount();

    setUser(admin);
    render(
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>,
    );
    expect(screen.getByText("Users and roles")).toBeInTheDocument();
  });
});

describe("session handling", () => {
  it("stores the access token in memory only", () => {
    setUser(analyst);

    expect(useAuth.getState().accessToken).toBe("token-in-memory");
    expect(Object.keys(window.localStorage)).toEqual([]);
  });

  it("refreshes after a 401 and retries the request once", async () => {
    setUser(analyst);
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      calls.push(url);
      if (url === "/api/v1/auth/refresh") {
        return new Response(JSON.stringify({ access_token: "new-token", expires_at: future, user: analyst }), { status: 200 });
      }
      return new Response("{}", { status: calls.length === 1 ? 401 : 200 });
    });

    const response = await apiFetch("/api/v1/dashboard/sales");

    expect(response.status).toBe(200);
    expect(calls).toEqual(["/api/v1/dashboard/sales", "/api/v1/auth/refresh", "/api/v1/dashboard/sales"]);
    expect(useAuth.getState().accessToken).toBe("new-token");
  });

  it("clears the session when the refresh cookie is rejected", async () => {
    setUser(analyst);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 401 }));

    expect(await refreshSession()).toBe(false);
    expect(useAuth.getState().status).toBe("anonymous");
  });

  it("reports a wrong password with the server's safe message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Invalid email or password" }), { status: 401 }));

    await expect(login("a@b.co", "wrong")).rejects.toThrow("Invalid email or password");
  });
});

describe("chat stream", () => {
  it("calls the handlers for steps and the final result", async () => {
    setUser(analyst);
    const body = 'event: step\ndata: {"state":"executing","elapsed_ms":12}\n\nevent: result\ndata: {"decision":"allowed","answer_text":"Done"}\n\n';
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(body));
        controller.close();
      },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(stream, { status: 200 }));
    const steps: string[] = [];
    const results: string[] = [];

    await act(async () => {
      await streamQuestion("revenue", null, {
        onStep: (state) => steps.push(state),
        onResult: (payload) => results.push(payload.answer_text ?? ""),
        onError: () => undefined,
      });
    });

    await waitFor(() => expect(results).toEqual(["Done"]));
    expect(steps).toEqual(["executing"]);
  });
});
