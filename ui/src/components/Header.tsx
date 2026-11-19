import { useAuth } from "../auth/AuthProvider";

const ROLE_LABEL: Record<string, string> = {
  store_user: "Store",
  l2_engineer: "L2 engineer",
  vendor_approver: "Vendor approver",
  l1_agent: "L1 agent",
  admin: "Admin",
};

export function Header() {
  const { who, logout } = useAuth();
  const role = who.roles.find((r) => r in ROLE_LABEL);
  return (
    <header className="topbar">
      <div className="brand">
        <span className="logo" aria-hidden="true">SW</span>
        <span>ServeWell IT Support</span>
      </div>
      <div className="who">
        <span className="who-name">
          {who.storeId ?? who.username}
          {role && <span className="pill">{ROLE_LABEL[role]}</span>}
        </span>
        <button className="btn ghost" onClick={logout}>
          Sign out
        </button>
      </div>
    </header>
  );
}
