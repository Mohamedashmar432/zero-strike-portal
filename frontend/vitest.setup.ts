import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Without globals: true, RTL's auto-cleanup-on-afterEach detection never fires (it only
// looks for a global `afterEach`), so each test would leak the previous test's DOM.
afterEach(() => {
  cleanup();
});
