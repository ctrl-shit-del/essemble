import { OrganiserShell } from "@/components/shell/OrganiserShell";
import { RequireRole } from "@/components/auth/RequireRole";

export default function OrganiserLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Admins are not organisers here: they own venues, they do not schedule
  // shows. Letting them in would show a catalogue that is never theirs.
  return (
    <RequireRole allow={["organiser"]}>
      <OrganiserShell>{children}</OrganiserShell>
    </RequireRole>
  );
}
