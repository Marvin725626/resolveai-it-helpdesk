import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./resolve.css";
import App from "./ResolveApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
