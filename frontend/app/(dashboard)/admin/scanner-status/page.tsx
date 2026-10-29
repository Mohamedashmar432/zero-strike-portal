import { redirect } from "next/navigation";

// Scanner status now lives in the Scanner section of the Operations page.
export default function ScannerStatusRedirect() {
  redirect("/admin/operations#scanner");
}
