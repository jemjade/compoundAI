// React·Routing·TanStack Query를 연결하는 Browser 진입점이다.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5_000 },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </AppErrorBoundary>
  </StrictMode>,
);
