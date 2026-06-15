import React, { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { apiErr } from "../lib/api";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (user && user !== false) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(apiErr(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen bg-slate-50">
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-between bg-gradient-to-br from-[#4A90E2] to-[#8B5CF6] p-12 text-white">
        <img src="/brand/homeivf-logo.svg" alt="HomeIVF" className="h-12 w-fit rounded-xl bg-white/95 p-2" />
        <div>
          <h1 className="font-display text-4xl sm:text-5xl font-extrabold leading-tight">
            Bringing Life Home,
            <br />
            one lead at a time.
          </h1>
          <p className="mt-4 max-w-md text-white/85 text-sm md:text-base">
            The HomeIVF CRM — your complete lead management, follow-up and conversion engine.
          </p>
        </div>
        <p className="text-xs uppercase tracking-[0.2em] text-white/70">Powered by TifTech</p>
      </div>
      <div className="flex w-full lg:w-1/2 items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <img src="/brand/homeivf-logo.svg" alt="HomeIVF" className="h-12 mb-8 lg:hidden" />
          <h2 className="font-display text-2xl sm:text-3xl font-extrabold text-slate-900">Welcome back</h2>
          <p className="mt-1 text-sm text-slate-600">Sign in to HomeIVF CRM</p>
          <form onSubmit={submit} className="mt-8 space-y-4">
            <div>
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Email</label>
              <input
                data-testid="login-email-input"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="hivf-input mt-1.5"
                placeholder="you@homeivf.com"
              />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Password</label>
              <input
                data-testid="login-password-input"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="hivf-input mt-1.5"
                placeholder="••••••••"
              />
            </div>
            {error && (
              <p data-testid="login-error" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-600">
                {error}
              </p>
            )}
            <button data-testid="login-submit-button" type="submit" disabled={loading} className="hivf-btn-primary w-full justify-center py-2.5">
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <p className="mt-10 text-center text-xs uppercase tracking-[0.2em] text-slate-400 lg:hidden">Powered by TifTech</p>
        </div>
      </div>
    </div>
  );
}
