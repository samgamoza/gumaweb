"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Logo } from "@/components/logo";
import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { ApiError, api, tokens } from "@/lib/api";
import type { PublicSiteInfo, TokenPair } from "@/lib/types";

type Method = "email" | "sms" | "business_identity";

interface Started { claim_id: string; status: string; method: Method; message: string }

function ClaimFlow() {
  const { subdomain } = useParams<{ subdomain: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const [site, setSite] = useState<PublicSiteInfo | null>(null);
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState({ name: "", email: "", phone: "", registration: "" });
  const [method, setMethod] = useState<Method>("email");
  const [started, setStarted] = useState<Started | null>(null);
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<PublicSiteInfo>(`/public/sites/${subdomain}`, { auth: false })
      .then(setSite)
      .catch(() => setLoadError("We couldn't find a website at this address."));
  }, [subdomain]);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<Started>("/claims", {
        auth: false,
        body: {
          subdomain,
          claimant_name: form.name,
          claimant_email: form.email,
          claimant_phone: form.phone || null,
          method,
          evidence: method === "business_identity" ? { registration_number: form.registration } : {},
          ref: search.get("ref"),
        },
      });
      setStarted(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function verifyOtp(e: React.FormEvent) {
    e.preventDefault();
    if (!started) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ status: string; message: string; tokens: TokenPair | null }>("/claims/verify", {
        auth: false,
        body: { claim_id: started.claim_id, otp, password: password || null },
      });
      if (result.tokens) {
        tokens.set(result.tokens);
        router.replace("/portal");
      } else {
        setStarted({ ...started, status: result.status, message: result.message });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl px-5 py-10">
      <Logo />
      {loadError && <div className="mt-10"><Alert>{loadError}</Alert></div>}
      {site && (
        <>
          <h1 className="mt-10 text-3xl font-semibold tracking-tight">Claim {site.business_name}</h1>
          <p className="mt-2 text-stone-600">
            {[site.city, site.province].filter(Boolean).join(", ")}
            {site.url && (
              <> · <a className="text-brand-700 underline" href={site.url} target="_blank" rel="noopener">View website</a></>
            )}
          </p>

          {site.is_claimed ? (
            <div className="mt-8"><Alert tone="amber">This website has already been claimed by its owner.</Alert></div>
          ) : !started ? (
            <Card className="mt-8">
              <form onSubmit={start} className="grid gap-4">
                <Field label="Your name">
                  <Input required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </Field>
                <Field label="Email" hint={site.masked_email ? `Fastest approval: use the email we have on record (${site.masked_email}).` : undefined}>
                  <Input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </Field>
                <fieldset className="grid gap-2 text-sm">
                  <legend className="mb-1.5 font-medium">Verify ownership by</legend>
                  {([
                    ["email", "Email link"],
                    ["sms", `SMS code${site.masked_phone ? ` (number on record ends ${site.masked_phone.slice(-4)})` : ""}`],
                    ["business_identity", "Business registration (reviewed by our team)"],
                  ] as [Method, string][]).map(([value, label]) => (
                    <label key={value} className="flex items-center gap-2">
                      <input type="radio" name="method" value={value} checked={method === value} onChange={() => setMethod(value)} className="accent-brand-600" />
                      {label}
                    </label>
                  ))}
                </fieldset>
                {method === "sms" && (
                  <Field label="Mobile number">
                    <Input type="tel" required value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
                  </Field>
                )}
                {method === "business_identity" && (
                  <Field label="DTI / SEC registration number">
                    <Input required value={form.registration} onChange={(e) => setForm({ ...form, registration: e.target.value })} />
                  </Field>
                )}
                <Alert>{error}</Alert>
                <Button type="submit" busy={busy}>Claim this website</Button>
                <p className="text-xs text-stone-500">Claiming is free. You can remove the website at any time.</p>
              </form>
            </Card>
          ) : started.method === "sms" && started.status === "pending_verification" ? (
            <Card className="mt-8" title="Enter your code">
              <form onSubmit={verifyOtp} className="grid gap-4">
                <p className="text-sm text-stone-600">{started.message}</p>
                <Field label="6-digit code">
                  <Input inputMode="numeric" pattern="\d{6}" required value={otp} onChange={(e) => setOtp(e.target.value)} />
                </Field>
                <Field label="Create a password" hint="At least 10 characters. Leave blank if you already have an account.">
                  <Input type="password" minLength={10} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
                </Field>
                <Alert>{error}</Alert>
                <Button type="submit" busy={busy}>Verify</Button>
              </form>
            </Card>
          ) : (
            <div className="mt-8"><Alert tone="green">{started.message}</Alert></div>
          )}
        </>
      )}
    </div>
  );
}

export default function ClaimPage() {
  return (
    <Suspense>
      <ClaimFlow />
    </Suspense>
  );
}
