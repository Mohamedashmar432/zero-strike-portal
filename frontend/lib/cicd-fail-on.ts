export type FailOn = "none" | "critical" | "high";

export const FAIL_ON_OPTIONS: { value: FailOn; label: string; description: string }[] = [
  { value: "none", label: "Warn only", description: "Findings never fail the pipeline; critical or high ones raise a red warning." },
  { value: "critical", label: "Fail on critical", description: "The pipeline fails if any critical finding is found." },
  { value: "high", label: "Fail on critical or high", description: "The pipeline fails if any critical or high finding is found." },
];
