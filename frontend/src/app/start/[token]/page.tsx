"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/logo";
import { Alert, Button, Card, Field, Input, Textarea } from "@/components/ui";
import { ApiError, api, tokens } from "@/lib/api";
import type { StartDetails, StartInfo, TokenPair } from "@/lib/types";

// Private claim link (owner-triggered publishing): the owner sees their private draft, confirms their details,
// and claims it. Verifying with the email or phone we have on record publishes the site at once.

type Method = "email" | "sms";
interface Started { claim_id: string; status: string; method: Method; message: string }

interface DetailsForm { name: string; description: string; address: string; facebook: string; services: string; phone: string; email: string }

function toForm(d: StartDetails): DetailsForm {
  return {
    name: d.name, description: d.description ?? "", address: d.address ?? "", facebook: d.facebook ?? "",
    services: d.services.join(", "), phone: d.phone ?? "", email: d.email ?? "",
  };
}

function message(err: unknown) {
  return err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
}

export default function StartPage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const [info, setInfo] = useState<StartInfo | null>(null);
  const [loadError, setLoadError] = useState("");
  const [details, setDetails] = useState<DetailsForm | null>(null);
  const [saved, setSaved] = useState<DetailsForm | null>(null);
  const [previewKey, setPreviewKey] = useState(0);
  const [claimant, setClaimant] = useState({ name: "", email: "", phone: "" });
  const [method, setMethod] = useState<Method>("email");
  const [started, setStarted] = useState<Started | null>(null);
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [detailsError, setDetailsError] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "claim" | "verify">("");

  useEffect(() => {
    api<StartInfo>(`/public/start/${token}`, { auth: false })
      .then((data) => { setInfo(data); setDetails(toForm(data.details)); setSaved(toForm(data.details)); })
      .catch((err) => setLoadError(
        err instanceof ApiError && err.status === 410
          ? "This link has expired. Reply to our email and we'll send you a new one."
          : "We couldn't open this link. Please check that you copied all of it.",
      ));
  }, [token]);

  async function saveDetails(e: React.FormEvent) {
    e.preventDefault();
    if (!details || !saved) return;
    const changed: Record<string, unknown> = {};
    for (const key of Object.keys(details) as (keyof DetailsForm)[]) {
      if (details[key] === saved[key]) continue;
      changed[key] = key === "services"
        ? details.services.split(",").map((s) => s.trim()).filter(Boolean)
        : details[key] || null;
    }
    if (!Object.keys(changed).length) { setNotice("Nothing to update."); return; }
    setBusy("save"); setDetailsError(""); setNotice("");
    try {
      const data = await api<StartInfo>(`/public/start/${token}/details`, { method: "PATCH", auth: false, body: changed });
      setInfo(data); setDetails(toForm(data.details)); setSaved(toForm(data.details));
      setPreviewKey((k) => k + 1);
      setNotice("Saved. Your preview is updated.");
    } catch (err) {
      setDetailsError(message(err));
    } finally {
      setBusy("");
    }
  }

  async function claim(e: React.FormEvent) {
    e.preventDefault();
    setBusy("claim"); setError("");
    try {
      setStarted(await api<Started>(`/public/start/${token}/claim`, {
        auth: false,
        body: { claimant_name: claimant.name, claimant_email: claimant.email, claimant_phone: claimant.phone || null, method },
      }));
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy("");
    }
  }

  async function verifyOtp(e: React.FormEvent) {
    e.preventDefault();
    if (!started) return;
    setBusy("verify"); setError("");
    try {
      const result = await api<{ status: string; message: string; tokens: TokenPair | null }>("/claims/verify", {
        auth: false, body: { claim_id: started.claim_id, otp, password: password || null },
      });
      if (result.tokens) {
        tokens.set(result.tokens);
        router.replace("/portal");
      } else {
        setStarted({ ...started, status: result.status, message: result.message });
      }
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy("");
    }
  }

  if (loadError) {
    return <div className="mx-auto max-w-xl px-5 py-10"><Logo /><div className="mt-10"><Alert>{loadError}</Alert></div></div>;
  }
  if (!info || !details) {
    return <div className="mx-auto max-w-xl px-5 py-10"><Logo /><p className="mt-10 text-stone-500">Loading your website…</p></div>;
  }

  const place = [info.city, info.province].filter(Boolean).join(", ");
  const set = (key: keyof DetailsForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setDetails({ ...details, [key]: e.target.value });

  return (
    <div className="mx-auto max-w-7xl px-5 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <Logo />
        <span className="text-xs text-stone-500">Private preview: only people with this link can see it.</span>
      </header>

      <h1 className="mt-6 text-2xl font-semibold tracking-tight sm:text-3xl">
        {info.status === "claimed" ? `${info.business_name} is claimed` : `Your website is ready, ${info.business_name}`}
      </h1>
      {place && <p className="mt-1 text-stone-600">{place}</p>}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="overflow-hidden rounded-xl border border-line bg-white">
          <iframe
            key={previewKey}
            src={info.preview_url}
            title={`Preview of the ${info.business_name} website`}
            className="h-[70vh] w-full lg:h-[calc(100vh-11rem)]"
            sandbox="allow-same-origin allow-scripts"
            referrerPolicy="no-referrer"
          />
        </div>

        <div className="grid content-start gap-6">
          {info.status === "claimed" ? (
            <Alert tone="green">This website has been claimed and is live. The owner can sign in to manage it.</Alert>
          ) : (
            <>
              <Card title="1. Check your details">
                <form onSubmit={saveDetails} className="grid gap-3">
                  <Field label="Business name"><Input required minLength={2} value={details.name} onChange={set("name")} /></Field>
                  <Field label="Services" hint="Separate with commas."><Input value={details.services} onChange={set("services")} /></Field>
                  <Field label="About your business"><Textarea rows={3} maxLength={2000} value={details.description} onChange={set("description")} /></Field>
                  <Field label="Address"><Input value={details.address} onChange={set("address")} /></Field>
                  <Field label="Phone" hint={info.masked_phone ? `On record: ${info.masked_phone}. Leave blank to keep it.` : undefined}>
                    <Input type="tel" value={details.phone} onChange={set("phone")} />
                  </Field>
                  <Field label="Email" hint={info.masked_email ? `On record: ${info.masked_email}. Leave blank to keep it.` : undefined}>
                    <Input type="email" value={details.email} onChange={set("email")} />
                  </Field>
                  <Field label="Facebook page"><Input value={details.facebook} onChange={set("facebook")} /></Field>
                  {notice && <Alert tone="green">{notice}</Alert>}
                  <Alert>{detailsError}</Alert>
                  <Button type="submit" variant="secondary" busy={busy === "save"}>Save and update preview</Button>
                </form>
              </Card>

              <Card title="2. Claim your website">
                {info.pending_claim && !started && (
                  <div className="mb-4"><Alert tone="amber">A claim for this business is already in progress. Check your email or phone.</Alert></div>
                )}
                {!started ? (
                  <form onSubmit={claim} className="grid gap-3">
                    <Field label="Your name">
                      <Input required minLength={2} value={claimant.name} onChange={(e) => setClaimant({ ...claimant, name: e.target.value })} />
                    </Field>
                    <Field label="Your email" hint={info.masked_email ? `Use ${info.masked_email} (the email we wrote to) and your site goes live right away.` : undefined}>
                      <Input type="email" required value={claimant.email} onChange={(e) => setClaimant({ ...claimant, email: e.target.value })} />
                    </Field>
                    <fieldset className="grid gap-2 text-sm">
                      <legend className="mb-1.5 font-medium">Confirm it&apos;s you by</legend>
                      {([["email", "Email link"], ["sms", `SMS code${info.masked_phone ? ` to the number ending ${info.masked_phone.slice(-4)}` : ""}`]] as [Method, string][]).map(([value, label]) => (
                        <label key={value} className="flex items-center gap-2">
                          <input type="radio" name="method" value={value} checked={method === value} onChange={() => setMethod(value)} className="accent-brand-600" />
                          {label}
                        </label>
                      ))}
                    </fieldset>
                    {method === "sms" && (
                      <Field label="Mobile number">
                        <Input type="tel" required value={claimant.phone} onChange={(e) => setClaimant({ ...claimant, phone: e.target.value })} />
                      </Field>
                    )}
                    <Alert>{error}</Alert>
                    <Button type="submit" busy={busy === "claim"}>Claim my website</Button>
                    <p className="text-xs text-stone-500">Free. Your website goes live when you claim it, and you can change anything afterwards.</p>
                  </form>
                ) : started.method === "sms" && started.status === "pending_verification" ? (
                  <form onSubmit={verifyOtp} className="grid gap-3">
                    <p className="text-sm text-stone-600">{started.message}</p>
                    <Field label="6-digit code">
                      <Input inputMode="numeric" pattern="\d{6}" required value={otp} onChange={(e) => setOtp(e.target.value)} />
                    </Field>
                    <Field label="Create a password" hint="At least 10 characters. Leave blank if you already have an account.">
                      <Input type="password" minLength={10} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
                    </Field>
                    <Alert>{error}</Alert>
                    <Button type="submit" busy={busy === "verify"}>Verify and publish</Button>
                  </form>
                ) : (
                  <Alert tone="green">{started.message}</Alert>
                )}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
