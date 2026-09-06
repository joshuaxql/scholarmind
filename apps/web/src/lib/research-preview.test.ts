import { expect, it } from "vitest";
import { researchPreview } from "./research-preview";

it("shows incomplete prose without showing JSON keys or unvalidated citations", () => {
  expect(researchPreview('{"overview":"An emerging field')).toEqual([{ key: "overview", text: "An emerging field" }]);
  expect(researchPreview('{"overview":"Done","method')).toEqual([{ key: "overview", text: "Done" }]);
  expect(researchPreview('{"themes":[{"name":"Theme","paper_ids":["P999"]}]}')).toEqual([{ key: "name", text: "Theme" }]);
});

it("handles escaped quotes, Unicode, and partial search phrases", () => {
  expect(researchPreview('{"overview":"A \\"quoted')).toEqual([{ key: "overview", text: 'A "quoted' }]);
  expect(researchPreview('{"overview":"\\u4e2d\\u65')).toEqual([{ key: "overview", text: "中" }]);
  expect(researchPreview('{"terms":["first term","second', true)).toEqual([
    { key: "terms", text: "first term" }, { key: "terms", text: "second" },
  ]);
});
