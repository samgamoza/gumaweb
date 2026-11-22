"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Logo } from "@/components/logo";
import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { ApiError, api, tokens } from "@/lib/api";
import type { TokenPair } from "@/lib/types";

function VerifyForm() {
  const token = useSearchParams().get("token");
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{ status: string; message: string; tokens: TokenPair | null }>("/claims/verify", {
        auth: false,
        body: { token, password: password || null },
      });
      if (result.tokens) {
        tokens.set(result.tokens);
        router.replace("/portal");
        return;
      }
      setDone(result.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (!token) return <Alert>This verification link is incomplete. Please use the link from your email.</Alert>;
  if (done) return <Alert tone="green">{done}</Alert>;

  return (
    <Card title="Confirm ownership">
      <form onSubmit={onSubmit} className="grid gap-4">
        <p className="text-sm text-stone-600">Create a password to manage your website. If you already have a GumaWeb account, leave it blank.</p>
        <Field label="Password" hint="At least 10 characters.">
          <Input type="password" minLength={10} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Alert>{error}</Alert>
        <Button type="submit" busy={busy}>Verify and continue</Button>
      </form>
    </Card>
  );
}

export default function VerifyPage() {
  return (
    <div className="mx-auto max-w-md px-5 py-10">
      <Logo />
      <h1 className="mb-6 mt-10 text-2xl font-semibold tracking-tight">Verify your claim</h1>
      <Suspense>
        <VerifyForm />
      </Suspense>
    </div>
  );
}
