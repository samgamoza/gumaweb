"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/logo";
import { Alert, Badge, Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

interface BookingSummary { business_name: string; service: string; when: string; status: string; cancellable: boolean }

export default function ManageBookingPage() {
  const { token } = useParams<{ token: string }>();
  const [booking, setBooking] = useState<BookingSummary | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<BookingSummary>(`/public/booking/${token}`, { auth: false }).then(setBooking)
      .catch(() => setError("We couldn't find this booking. The link may be incomplete."));
  }, [token]);

  return (
    <div className="mx-auto max-w-md px-5 py-10">
      <Logo />
      <h1 className="mb-6 mt-10 text-2xl font-semibold tracking-tight">Your booking</h1>
      {error && <Alert>{error}</Alert>}
      {booking && (
        <Card>
          <div className="grid gap-3 text-sm">
            <div className="flex items-center justify-between"><span className="text-lg font-semibold">{booking.business_name}</span><Badge>{booking.status}</Badge></div>
            <div><span className="text-stone-500">Service</span><div className="font-medium">{booking.service}</div></div>
            <div><span className="text-stone-500">When</span><div className="font-medium">{booking.when}</div></div>
            {booking.cancellable && (
              <Button variant="danger" busy={busy} onClick={async () => {
                if (!window.confirm("Cancel this booking?")) return;
                setBusy(true);
                try {
                  setBooking(await api<BookingSummary>(`/public/booking/${token}/cancel`, { auth: false, body: {} }));
                } catch (e) {
                  setError(e instanceof ApiError ? e.message : "Could not cancel");
                } finally {
                  setBusy(false);
                }
              }}>Cancel booking</Button>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
