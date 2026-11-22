"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Logo } from "@/components/logo";
import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError, login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await login(email, password);
      router.replace(user.role === "customer" ? "/portal" : "/admin");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to reach the server");
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh place-items-center px-5">
      <div className="w-full max-w-sm">
        <Logo />
        <h1 className="mt-8 text-2xl font-semibold tracking-tight">Sign in</h1>
        <p className="mt-1 text-sm text-stone-600">Business owners and GumaWeb staff.</p>
        <form onSubmit={onSubmit} className="mt-6 grid gap-4">
          <Field label="Email">
            <Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password">
            <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <Alert>{error}</Alert>
          <Button type="submit" busy={busy}>Sign in</Button>
        </form>
      </div>
    </div>
  );
}
