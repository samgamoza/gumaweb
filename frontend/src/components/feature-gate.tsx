"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { FeatureAccess } from "@/lib/types";

const UPSELL: Record<string, { plan: string; label: string; pitch: string }> = {
  crm: { plan: "business", label: "Business Plus", pitch: "Every inquiry from your website, bookings and chat, in one simple pipeline." },
  booking: { plan: "business", label: "Business Plus", pitch: "Let customers book appointments on your website, around the clock." },
  ai_chatbot: { plan: "ai", label: "AI", pitch: "An assistant on your website that answers questions from your own information and collects leads." },
  automation: { plan: "business", label: "Business Plus", pitch: "Thank new leads, remind customers before appointments, and follow up automatically." },
  integrations: { plan: "business", label: "Business Plus", pitch: "Connect GumaWeb to your other tools with API keys and webhooks." },
  voice_receptionist: { plan: "voice_ai", label: "Voice AI", pitch: "An AI receptionist that answers your phone, books appointments and takes messages." },
};

/** Renders children only when the plan includes `feature`; otherwise an upgrade card. */
export function FeatureGate({ feature, children }: { feature: string; children: React.ReactNode }) {
  const [access, setAccess] = useState<FeatureAccess | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<FeatureAccess>("/customer/features").then(setAccess).catch((e) => setError(e.message));
  }, []);

  if (error) return <Alert tone="amber">{error}</Alert>;
  if (!access) return null;
  if (access.features[feature]) return <>{children}</>;

  const upsell = UPSELL[feature];
  return (
    <Card>
      <div className="grid max-w-xl gap-3 py-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Available on {upsell.label}</p>
        <h2 className="text-xl font-semibold tracking-tight">{upsell.pitch}</h2>
        <p className="text-sm text-stone-600">
          You&apos;re on the {access.plan} plan. Inquiries are already being saved, so you&apos;ll see your history as soon as you upgrade.
        </p>
        <div>
          <Button busy={busy} onClick={async () => {
            setBusy(true);
            try {
              await api("/customer/subscription", { body: { plan: upsell.plan } });
              setAccess(await api<FeatureAccess>("/customer/features"));
            } catch (e) {
              setError(e instanceof ApiError ? e.message : "Upgrade failed");
            } finally {
              setBusy(false);
            }
          }}>Upgrade to {upsell.label}</Button>
        </div>
      </div>
    </Card>
  );
}
