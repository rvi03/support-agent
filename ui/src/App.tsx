import { AuthProvider, useAuth } from "./auth/AuthProvider";
import { Header } from "./components/Header";
import { StoreHome } from "./screens/StoreHome";
import { Queue } from "./screens/Queue";

function Home() {
  const { who } = useAuth();
  // The role in the token picks the home screen (S13 step 2).
  if (who.roles.includes("l2_engineer") || who.roles.includes("vendor_approver")) return <Queue />;
  if (who.roles.includes("store_user")) return <StoreHome />;
  return <p className="empty muted">This sign-in has no Demo UI screen (store, L2 or vendor roles only).</p>;
}

export function App() {
  return (
    <AuthProvider>
      <Header />
      <main id="main">
        <Home />
      </main>
    </AuthProvider>
  );
}
