import { useEffect, useState } from "react";

type ApiStatus = "checking" | "available" | "unavailable";

export function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/v1/health", { signal: controller.signal })
      .then((response) => setApiStatus(response.ok ? "available" : "unavailable"))
      .catch(() => {
        if (!controller.signal.aborted) {
          setApiStatus("unavailable");
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <main>
      <h1>Meridian Data Copilot</h1>
      <p>Governed natural language analytics. The application workspace is under construction.</p>
      <p>
        API status: <strong>{apiStatus}</strong>
      </p>
    </main>
  );
}
