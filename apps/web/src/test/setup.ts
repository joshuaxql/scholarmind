import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(cleanup);
if (typeof Element !== "undefined") Element.prototype.scrollTo = vi.fn();
