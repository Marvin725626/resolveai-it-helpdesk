import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./resolve.css";
import App from "./ResolveApp";
import InviteAccept from "./InviteAccept";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {window.location.pathname.replace(/\/$/, "") === "/invite" ? <InviteAccept /> : <App />}
  </StrictMode>
);
