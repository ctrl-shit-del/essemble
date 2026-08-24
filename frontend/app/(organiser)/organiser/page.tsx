import { Card, CardBody } from "@/components/ui/Card";

/** Placeholder so the organiser shell has content to frame in pass 1. */
export default function OrganiserOverview() {
  return (
    <div>
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl tracking-tight text-text">
            Overview
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            Catalogue, schedule and venue requests.
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: "Upcoming shows", value: "—" },
          { label: "Events", value: "—" },
          { label: "Pending requests", value: "—" },
          { label: "Seats sold, 7d", value: "—" },
        ].map((metric) => (
          <Card key={metric.label}>
            <CardBody className="p-4">
              <p className="text-[11px] uppercase tracking-[0.14em] text-muted">
                {metric.label}
              </p>
              {/* Amber is for key metrics -- one of its few sanctioned uses. */}
              <p className="mt-2 font-display text-2xl text-accent">
                {metric.value}
              </p>
            </CardBody>
          </Card>
        ))}
      </div>

      <p className="mt-8 text-[13px] text-muted">
        Wired up in a later pass.
      </p>
    </div>
  );
}
