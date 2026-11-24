import { ArrowLeft, Lock } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { api, type SessionState } from "../api/client";
import { Logo } from "../components/Logo";

export default function Login({ onSignedIn, onBack }: { onSignedIn: (session: SessionState) => void; onBack: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const userField = useRef<HTMLInputElement>(null);

  useEffect(() => { userField.current?.focus(); }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onSignedIn(await api.login(username.trim(), password));
    } catch (e) {
      setError((e as Error).message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="on-shell flex min-h-full items-center justify-center bg-shell px-4 py-10 text-shell-text">
      <div className="w-full max-w-sm">
        <button type="button" onClick={onBack} className="mb-6 inline-flex items-center gap-1.5 text-xs text-shell-muted hover:text-white"><ArrowLeft size={14} /> Back to home</button>
        <div className="rounded-xl border border-shell-line bg-shell-raised p-6 shadow-2xl shadow-black/40">
          <Logo size={32} tagline />
          <h1 className="mt-6 text-lg font-semibold text-white">Sign in to the workbench</h1>
          <p className="mt-1 text-xs leading-5 text-shell-muted">Case files, CCTV evidence and the registry are only available to signed-in investigators.</p>
          <form className="mt-5 space-y-3" onSubmit={submit}>
            <label className="block text-xs font-medium text-shell-text">Username
              <input ref={userField} className="field mt-1" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
            </label>
            <label className="block text-xs font-medium text-shell-text">Password
              <input className="field mt-1" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            {error && <p role="alert" className="rounded-evidence border border-rose-400/40 bg-rose-500/10 px-2.5 py-2 text-xs text-rose-200">{error}</p>}
            <button type="submit" className="btn btn-primary w-full" disabled={busy || !username || !password}><Lock size={14} /> {busy ? "Signing in…" : "Sign in"}</button>
          </form>
        </div>
      </div>
    </main>
  );
}
