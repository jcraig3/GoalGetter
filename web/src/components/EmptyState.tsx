/**
 * Shown wherever a page has nothing to display.
 *
 * A blank area reads as broken, so an empty state always says what belongs
 * here and what to do next. This is also how unbuilt pages are represented —
 * honestly labelled rather than filled with placeholder data that looks real.
 */
export default function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-edge px-6 py-16 text-center">
      <p className="text-content">{title}</p>
      {description && (
        <p className="mx-auto mt-2 max-w-md text-sm text-content-muted">
          {description}
        </p>
      )}
      {action && <div className="mt-6 flex justify-center">{action}</div>}
    </div>
  );
}
