import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";
import SiteLayout from "./site/SiteLayout";
import Home from "./site/pages/Home";
import { Skeleton } from "./components/ui";

// Routes other than the home page are split into their own chunks.
const { Platform, Solutions, Security, Benchmarks, Resources, About } = {
  Platform: lazy(() => import("./site/pages/ContentPages").then((m) => ({ default: m.Platform }))),
  Solutions: lazy(() => import("./site/pages/ContentPages").then((m) => ({ default: m.Solutions }))),
  Security: lazy(() => import("./site/pages/ContentPages").then((m) => ({ default: m.Security }))),
  Benchmarks: lazy(() => import("./site/pages/ContentPages").then((m) => ({ default: m.Benchmarks }))),
  Resources: lazy(() => import("./site/pages/ContentPages").then((m) => ({ default: m.Resources }))),
  About: lazy(() => import("./site/pages/ContentPages").then((m) => ({ default: m.About }))),
};
const Contact = lazy(() => import("./site/pages/Contact"));
const { Privacy, Terms, Cookies, Accessibility, Attribution } = {
  Privacy: lazy(() => import("./site/pages/Legal").then((m) => ({ default: m.Privacy }))),
  Terms: lazy(() => import("./site/pages/Legal").then((m) => ({ default: m.Terms }))),
  Cookies: lazy(() => import("./site/pages/Legal").then((m) => ({ default: m.Cookies }))),
  Accessibility: lazy(() => import("./site/pages/Legal").then((m) => ({ default: m.Accessibility }))),
  Attribution: lazy(() => import("./site/pages/Legal").then((m) => ({ default: m.Attribution }))),
};
const NotFound = lazy(() => import("./site/pages/Status").then((m) => ({ default: m.NotFound })));
const AppRoutes = lazy(() => import("./app/AppRoutes"));

function PageFallback() {
  return (
    <div className="container-page py-16" aria-busy="true" aria-label="Loading page">
      <Skeleton className="h-10 w-2/3" />
      <Skeleton className="mt-6 h-4 w-full" />
      <Skeleton className="mt-3 h-4 w-5/6" />
    </div>
  );
}

export function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="app/*" element={<AppRoutes />} />
        <Route element={<SiteLayout />}>
          <Route index element={<Home />} />
          <Route path="platform" element={<Platform />} />
          <Route path="solutions" element={<Solutions />} />
          <Route path="security" element={<Security />} />
          <Route path="benchmarks" element={<Benchmarks />} />
          <Route path="resources" element={<Resources />} />
          <Route path="about" element={<About />} />
          <Route path="contact" element={<Contact />} />
          <Route path="legal/privacy" element={<Privacy />} />
          <Route path="legal/terms" element={<Terms />} />
          <Route path="legal/cookies" element={<Cookies />} />
          <Route path="legal/accessibility" element={<Accessibility />} />
          <Route path="legal/attribution" element={<Attribution />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
