"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AuthGuard, useUser } from "@/components/auth-guard";
import { Logo } from "@/components/logo";
import { Badge, Button, cx } from "@/components/ui";
import { logout } from "@/lib/api";

const NAV = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/discovery", label: "Discovery" },
  { href: "/admin/businesses", label: "Businesses" },
  { href: "/admin/websites", label: "Websites" },
  { href: "/admin/jobs", label: "Factory jobs" },
  { href: "/admin/claims", label: "Claims" },
  { href: "/admin/outreach", label: "Outreach" },
  { href: "/admin/suppressions", label: "Do-not-contact" },
  { href: "/admin/templates", label: "Templates" },
];

function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const user = useUser();
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[220px_1fr]">
      <aside className="border-b border-line bg-white md:sticky md:top-0 md:h-dvh md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-5 py-4 md:block">
          <Logo href="/admin" />
          <Button size="sm" variant="ghost" onClick={logout} className="md:hidden">Sign out</Button>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:pb-0">
          {NAV.map((item) => {
            const active = item.href === "/admin" ? pathname === "/admin" : pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href} className={cx(
                "whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium",
                active ? "bg-brand-50 text-brand-900" : "text-stone-600 hover:bg-stone-100 hover:text-ink",
              )}>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="absolute bottom-0 hidden w-[219px] border-t border-line p-4 text-xs md:block">
          <div className="truncate font-medium">{user.email}</div>
          <div className="mt-1 flex items-center justify-between">
            <Badge tone="gray">{user.role}</Badge>
            <button onClick={logout} className="text-stone-500 hover:text-ink">Sign out</button>
          </div>
        </div>
      </aside>
      <main className="min-w-0 px-5 py-8 md:px-8">{children}</main>
    </div>
  );
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard roles={["admin", "operator", "readonly"]}>
      <Shell>{children}</Shell>
    </AuthGuard>
  );
}
