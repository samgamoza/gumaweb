"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/logo";
import { Button, Input } from "@/components/ui";
import { api, money } from "@/lib/api";
import type { Plan } from "@/lib/types";

const STEPS = [
  { n: "01", title: "We find you", body: "We look for local businesses that customers can't find online yet." },
  { n: "02", title: "We build your site", body: "A professional, mobile-friendly website with your services and contact details." },
  { n: "03", title: "You claim it", body: "Verify you own the business by email or SMS. It's free." },
  { n: "04", title: "You grow", body: "Edit your content, receive leads, and add a custom domain when you're ready." },
];

export default function Home() {
  const router = useRouter();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [subdomain, setSubdomain] = useState("");

  useEffect(() => {
    api<Plan[]>("/billing/plans", { auth: false }).then(setPlans).catch(() => setPlans([]));
  }, []);

  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <Logo />
        <Link href="/login" className="text-sm font-medium text-stone-600 hover:text-ink">Sign in</Link>
      </header>

      <main>
        <section className="mx-auto max-w-6xl px-5 pb-20 pt-14 md:pt-24">
          <p className="text-sm font-semibold uppercase tracking-[0.14em] text-brand-700">For local businesses</p>
          <h1 className="mt-4 max-w-3xl text-4xl font-semibold leading-[1.05] tracking-tight md:text-6xl">
            We already built your website. <span className="text-brand-600">Claim it.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg text-stone-600">
            GumaWeb builds professional websites for businesses that don&apos;t have one yet. If we&apos;ve built
            yours, it&apos;s free to claim and yours to manage.
          </p>
          <form
            className="mt-10 flex max-w-lg flex-col gap-3 sm:flex-row"
            onSubmit={(e) => {
              e.preventDefault();
              const slug = subdomain.trim().toLowerCase().replace(/\.gumaweb\.io.*$/, "").replace(/^https?:\/\//, "");
              if (slug) router.push(`/claim/${encodeURIComponent(slug)}`);
            }}
          >
            <div className="flex h-11 flex-1 items-center rounded-lg border border-line bg-white pr-3 focus-within:border-brand-500">
              <Input
                aria-label="Your website address"
                placeholder="your-business"
                value={subdomain}
                onChange={(e) => setSubdomain(e.target.value)}
                className="h-full border-0 focus:border-0"
              />
              <span className="text-sm text-stone-400">.gumaweb.io</span>
            </div>
            <Button type="submit" className="h-11">Find my website</Button>
          </form>
        </section>

        <section className="border-y border-line bg-white">
          <div className="mx-auto grid max-w-6xl gap-px px-5 py-16 md:grid-cols-4 md:gap-10">
            {STEPS.map((s) => (
              <div key={s.n} className="py-4">
                <div className="font-mono text-sm text-brand-600">{s.n}</div>
                <h3 className="mt-2 font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm text-stone-600">{s.body}</p>
              </div>
            ))}
          </div>
        </section>

        {plans.length > 0 && (
          <section className="mx-auto max-w-6xl px-5 py-20">
            <h2 className="text-2xl font-semibold tracking-tight">Start free. Upgrade when it pays off.</h2>
            <div className="mt-8 grid gap-4 md:grid-cols-3 lg:grid-cols-5">
              {plans.map((p, i) => (
                <div key={p.code} className={`rounded-xl border bg-white p-5 ${i === 1 ? "border-brand-500 ring-1 ring-brand-500" : "border-line"}`}>
                  <div className="text-sm font-semibold">{p.name}</div>
                  <div className="mt-2 text-2xl font-semibold tabular-nums">
                    {p.price_monthly_cents ? money(p.price_monthly_cents, p.currency) : "Free"}
                    {p.price_monthly_cents > 0 && <span className="text-sm font-normal text-stone-500">/mo</span>}
                  </div>
                  <p className="mt-2 text-sm text-stone-600">{p.description}</p>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl justify-between px-5 py-6 text-sm text-stone-500">
          <span>© {new Date().getFullYear()} GumaWeb</span>
          <span>Part of Guma One</span>
        </div>
      </footer>
    </div>
  );
}
