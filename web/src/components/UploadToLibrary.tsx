import { useState } from 'react';

import { api, ApiError } from '../api';

/**
 * "Upload" beside a gallery of library pictures (Phase 27): the file goes into
 * the asset library and is chosen at once, so a picker that offered only the
 * library offers this computer too.
 */
export default function UploadToLibrary({
  accept = 'image/png,image/jpeg,image/webp,image/gif',
  onUploaded,
  className = '',
}: {
  accept?: string;
  onUploaded: (file: { digest: string; kind: string; name: string | null }) => void;
  className?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setProblem(null);
    try {
      onUploaded(
        await api<{ digest: string; kind: string; name: string | null }>('/api/assets', {
          method: 'POST',
          body: file,
          headers: { 'X-File-Name': encodeURIComponent(file.name) },
        }),
      );
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : 'Couldn’t upload that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className={`inline-flex flex-col ${className}`}>
      <label className="flex h-full min-h-12 cursor-pointer items-center justify-center rounded-md border border-dashed border-edge px-3 py-1 text-xs text-content-muted hover:border-brand hover:text-content">
        {busy ? 'Uploading…' : '+ Upload'}
        <input
          type="file"
          accept={accept}
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (file) void upload(file);
          }}
        />
      </label>
      {problem && <span className="mt-1 text-xs text-danger">{problem}</span>}
    </span>
  );
}
