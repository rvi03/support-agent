import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { User } from "oidc-client-ts";
import { completeLogin, userManager, whoFrom, type Who } from "./oidc";
import { makeApi, type Api } from "../api/client";

interface AuthValue {
  who: Who;
  api: Api;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const v = useContext(AuthContext);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [state, setState] = useState<"loading" | "out" | "in" | "error">("loading");
  const tokenRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    let live = true;
    completeLogin()
      .then((u) => {
        if (!live) return;
        setUser(u);
        setState(u && !u.expired ? "in" : "out");
      })
      .catch(() => live && setState("error"));
    const loaded = (u: User) => setUser(u);
    const gone = () => {
      setUser(null);
      setState("out");
    };
    userManager.events.addUserLoaded(loaded);
    userManager.events.addSilentRenewError(gone);
    userManager.events.addUserSignedOut(gone);
    return () => {
      live = false;
      userManager.events.removeUserLoaded(loaded);
      userManager.events.removeSilentRenewError(gone);
      userManager.events.removeUserSignedOut(gone);
    };
  }, []);

  tokenRef.current = user?.access_token;
  const api = useMemo(() => makeApi(() => tokenRef.current), []);
  const value = useMemo<AuthValue | null>(
    () =>
      user
        ? { who: whoFrom(user), api, logout: () => void userManager.signoutRedirect({ id_token_hint: user.id_token }) }
        : null,
    [user, api],
  );

  if (state === "loading") return <p className="center muted">Loading…</p>;
  if (state !== "in" || !value) return <Login failed={state === "error"} />;
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function Login({ failed }: { failed: boolean }) {
  return (
    <main className="login">
      <div className="login-card">
        <p className="eyebrow">ServeWell IT Support</p>
        <h1>Sign in</h1>
        <p className="muted">Store teams raise and follow tickets. IT engineers approve steps and take handoffs.</p>
        {failed && <p role="alert" className="notice">Sign-in did not complete. Please try again.</p>}
        <button className="btn primary" onClick={() => void userManager.signinRedirect()}>
          Sign in with ServeWell ID
        </button>
      </div>
    </main>
  );
}
