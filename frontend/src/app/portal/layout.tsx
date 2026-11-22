"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AuthGuard, useUser } from "@/components/auth-guard";
import { Logo } from "@/components/logo";
import { Button, cx } from "@/components/ui";
import { logout } from "@/lib/api";

const NAV = [
  { href: "/portal", label: "Website" },
  { href: "/portal/presence", label: "Online presence" },
  { href: "/portal/leads", label: "Leads & CRM" },
  { href: "/portal/bookings", label: "Bookings" },
  { href: "/portal/assistant", label: "AI assistant" },
  { href: "/portal/receptionist", label: "Receptionist" },
  { href: "/portal/automations", label: "Automations" },
  { href: "/portal/integrations", label: "Integrations" },
];

function Shell({ children }: { children: React.ReactNode }) {
  const user = useUser();
  const pathname = usePathname();
  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-3.5">
          <Logo href="/portal" />
          <div className="flex items-center gap-3 text-sm text-stone-600">
            <span className="hidden sm:inline">{user.email}</span>
            <Button size="sm" variant="ghost" onClick={logout}>Sign out</Button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-5xl gap-1 overflow-x-auto overflow-y-hidden px-5" aria-label="Portal">
          {NAV.map((item) => {
            const active = item.href === "/portal" ? pathname === "/portal" : pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href} className={cx(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium",
                active ? "border-brand-600 text-ink" : "border-transparent text-stone-500 hover:text-ink",
              )}>{item.label}</Link>
            );
          })}
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-5 py-8">{children}</main>
    </div>
  );
}

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard roles={["customer"]}>
      <Shell>{children}</Shell>
    </AuthGuard>
  );
}
