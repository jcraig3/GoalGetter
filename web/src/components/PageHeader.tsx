import { useDocumentTitle } from '../documentTitle';

export default function PageHeader({
  title,
  description,
  actions,
  tabTitle,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  /** The browser tab's, where the heading is not a name for the page — Home's
   *  is a greeting (Q2-24). */
  tabTitle?: string;
}) {
  // Every page in the shell has one of these, so this is where the tab's
  // title comes from.
  useDocumentTitle(tabTitle ?? title);
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-h1 text-content">{title}</h1>
        {description && (
          <p className="mt-1 text-content-muted">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
