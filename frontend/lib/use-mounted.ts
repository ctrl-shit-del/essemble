"use client";

import { useEffect, useState } from "react";

/**
 * False during SSR and on the client's FIRST render; true from the next
 * commit onward.
 *
 * This is what portals need. `createPortal` targets document.body, which does
 * not exist on the server, so a component that guards with
 * `typeof document === "undefined"` renders nothing server-side and then
 * renders the portal immediately during hydration -- React compares the two
 * trees, finds a node the server never sent, and throws a hydration
 * mismatch, discarding and re-rendering the tree.
 *
 * Gating on mount makes the first client render match the server exactly
 * (nothing), and the portal arrives on the following commit where React is no
 * longer reconciling against server HTML.
 */
export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}
