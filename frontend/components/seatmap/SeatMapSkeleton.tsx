import { Skeleton } from "@/components/ui/Skeleton";

/**
 * Loading state shaped like the thing being loaded.
 *
 * A spinner here would be worse than nothing: the seat grid is the entire
 * page, so a centred spinner tells you only that something is happening,
 * while a grid of the right proportions tells you what is arriving and stops
 * the layout jumping when it does.
 *
 * The row lengths are deliberately uneven, with a gap partway along, so the
 * placeholder implies a real hall with aisles rather than a perfect matrix.
 */
export function SeatMapSkeleton() {
  const rows = 10;
  const seatsPerRow = 16;

  return (
    <div className="rounded-xl border border-border bg-surface p-6" aria-hidden="true">
      <div className="mx-auto mb-8 h-1 w-2/3 rounded-full bg-surface-2" />
      <div className="mx-auto mb-8 h-2 w-32 rounded bg-surface-2" />

      <div className="space-y-2">
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <div key={rowIndex} className="flex items-center gap-2">
            <Skeleton className="h-3 w-4 shrink-0" />
            <div className="flex flex-1 gap-1.5">
              {Array.from({ length: seatsPerRow }).map((__, seatIndex) => (
                <div
                  key={seatIndex}
                  className="flex-1"
                  // The aisle, so the shape matches the real geometry.
                  style={{ marginLeft: seatIndex === 3 || seatIndex === 12 ? 12 : 0 }}
                >
                  <Skeleton className="aspect-square w-full rounded-[5px]" />
                </div>
              ))}
            </div>
            <Skeleton className="h-3 w-10 shrink-0" />
          </div>
        ))}
      </div>
    </div>
  );
}
