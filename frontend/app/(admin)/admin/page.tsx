import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

/** Placeholder so the admin shell has content to frame in pass 1. */
export default function AdminOverview() {
  return (
    <div>
      <div className="flex items-center gap-3">
        <h1 className="font-display text-2xl tracking-tight text-text">
          Overview
        </h1>
        <Badge tone="accent">1 pending</Badge>
      </div>
      <p className="mt-1 text-[13px] text-muted">
        Everything on this page is scoped to the venue selected in the header.
      </p>

      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {[
          { label: "Screens", value: "—" },
          { label: "Seats", value: "—" },
          { label: "Checked in today", value: "—" },
        ].map((metric) => (
          <Card key={metric.label}>
            <CardBody className="p-4">
              <p className="text-[11px] uppercase tracking-[0.14em] text-muted">
                {metric.label}
              </p>
              <p className="mt-2 font-display text-2xl text-accent">
                {metric.value}
              </p>
            </CardBody>
          </Card>
        ))}
      </div>

      <p className="mt-8 text-[13px] text-muted">Wired up in a later pass.</p>
    </div>
  );
}
