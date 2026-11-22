"use client";

import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, tokens } from "@/lib/api";
import type { Role, User } from "@/lib/types";

const UserContext = createContext<User | null>(null);

export function useUser(): User {
  const user = useContext(UserContext);
  if (!user) throw new Error("useUser must be used inside <AuthGuard>");
  return user;
}

export function AuthGuard({ roles, children }: { roles: Role[]; children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const roleKey = roles.join(",");

  useEffect(() => {
    const allowed = roleKey.split(",");
    if (!tokens.access) {
      router.replace("/login");
      return;
    }
    api<User>("/auth/me")
      .then((me) => {
        if (!allowed.includes(me.role)) {
          router.replace(me.role === "customer" ? "/portal" : "/admin");
          return;
        }
        setUser(me);
      })
      .catch(() => {
        tokens.clear();
        router.replace("/login");
      });
  }, [router, roleKey]);

  if (!user) {
    return (
      <div className="grid min-h-dvh place-items-center text-sm text-stone-500">
        <span className="size-5 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" aria-label="Loading" />
      </div>
    );
  }
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}
