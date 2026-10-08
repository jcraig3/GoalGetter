import { useState } from 'react';

import { api, ApiError } from '../api';
import type { HttpsSettings } from './hostingWays';

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

/** The two files IT sent, read in the browser and checked by the server. */
export default function CertificateFiles({
  files,
  onUploaded,
}: {
  files: HttpsSettings['files'];
  onUploaded: (settings: HttpsSettings) => void;
}) {
  const [certificate, setCertificate] = useState<File | null>(null);
  const [key, setKey] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function upload() {
    if (!certificate || !key) return;
    setBusy(true);
    setProblem(null);
    try {
      const settings = await api<HttpsSettings>('/api/hosting/certificate', {
        method: 'POST',
        body: JSON.stringify({ certificate: await readText(certificate), key: await readText(key) }),
      });
      setCertificate(null);
      setKey(null);
      onUploaded(settings);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : 'Couldn’t upload those.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-md bg-surface-raised p-3 text-sm">
      {files ? (
        <p className="text-content">
          {files.names.join(', ') || 'Uploaded'}
          <span className="text-content-subtle"> · until {shortDate(files.valid_until)}</span>
        </p>
      ) : (
        <p className="text-content-muted">None uploaded yet</p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-content-muted">
          Certificate
          <input
            type="file"
            accept=".pem,.crt,.cer"
            onChange={(e) => setCertificate(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm text-content-muted file:mr-3 file:rounded file:border file:border-edge file:bg-transparent file:px-2 file:py-1 file:text-sm file:text-content hover:file:bg-surface-hover"
          />
        </label>
        <label className="block text-xs text-content-muted">
          Key
          <input
            type="file"
            accept=".pem,.key"
            onChange={(e) => setKey(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm text-content-muted file:mr-3 file:rounded file:border file:border-edge file:bg-transparent file:px-2 file:py-1 file:text-sm file:text-content hover:file:bg-surface-hover"
          />
        </label>
      </div>
      {problem && <p className="text-danger">{problem}</p>}
      <button
        type="button"
        onClick={() => void upload()}
        disabled={busy || !certificate || !key}
        className="rounded-md border border-edge px-3 py-1 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
      >
        {busy ? 'Uploading…' : files ? 'Replace' : 'Upload'}
      </button>
    </div>
  );
}
