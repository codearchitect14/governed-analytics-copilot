// Load test for the cached dashboard path and the uncached chat path.
// Run: k6 run -e BASE_URL=http://localhost:8010 -e EMAIL=analyst@meridian.example -e PASSWORD=... loadtest/k6/api.js
// Thresholds mirror the latency targets in the project plan (dashboard p95 under 500 ms cached,
// chat p95 under 3 s). The chat scenario calls the model, so keep its rate low on free tiers.
import http from "k6/http";
import { check, fail, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8010";

export const options = {
  scenarios: {
    dashboard_cached: {
      executor: "constant-vus",
      vus: 20,
      duration: "2m",
      exec: "dashboard",
    },
    chat_uncached: {
      executor: "constant-arrival-rate",
      rate: 2,
      timeUnit: "1m",
      duration: "2m",
      preAllocatedVUs: 4,
      exec: "chat",
    },
  },
  thresholds: {
    "http_req_failed{scenario:dashboard_cached}": ["rate<0.01"],
    "http_req_duration{scenario:dashboard_cached}": ["p(95)<500"],
    "http_req_duration{scenario:chat_uncached}": ["p(95)<3000"],
  },
};

export function setup() {
  const res = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: __ENV.EMAIL, password: __ENV.PASSWORD }),
    { headers: { "Content-Type": "application/json" } },
  );
  if (res.status !== 200) {
    fail(`login failed with status ${res.status}`);
  }
  return { token: res.json("access_token") };
}

export function dashboard(data) {
  const headers = { Authorization: `Bearer ${data.token}` };
  const res = http.get(`${BASE_URL}/api/v1/dashboard/overview`, { headers });
  check(res, { "dashboard 200 or 304": (r) => r.status === 200 || r.status === 304 });
  sleep(0.5);
}

export function chat(data) {
  const headers = { Authorization: `Bearer ${data.token}`, "Content-Type": "application/json" };
  const res = http.post(
    `${BASE_URL}/api/v1/chat/query`,
    JSON.stringify({ question: "Revenue by month" }),
    { headers, timeout: "30s" },
  );
  check(res, { "chat responded": (r) => r.status === 200 });
}
