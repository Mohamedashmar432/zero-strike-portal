import { apiFetch } from "./client";

export type ScannerBinaryInfo = {
  version: string;
  os: string;
  arch: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  uploaded_at: string;
};

/**
 * Public (no auth needed) metadata for a published scanner binary. Rejects with `ApiError`;
 * `status === 404` means that version/platform has not been published on this portal.
 */
export function getScannerBinaryInfo(version = "latest", osArch = "linux-amd64") {
  return apiFetch<ScannerBinaryInfo>(
    `/downloads/zerostrike/${encodeURIComponent(version)}/${osArch}/info`
  );
}
