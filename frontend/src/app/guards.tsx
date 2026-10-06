import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { isAdmin, useAuth } from "../lib/auth-store";
import { Skeleton } from "../components/ui";

/** Shows the workspace only to signed in users. Waits while the first silent refresh runs. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuth((state) => state.status);
  const location = useLocation();
  if (status === "loading") {
    return (
      <div className="container-page py-12" aria-busy="true" aria-label="Checking your session">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="mt-6 h-40 w-full" />
      </div>
    );
  }
  if (status === "anonymous") {
    return <Navigate to="/app/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

/** Admin only pages. Other roles are sent back to the chat. */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const user = useAuth((state) => state.user);
  if (!isAdmin(user)) return <Navigate to="/app/chat" replace />;
  return <>{children}</>;
}
