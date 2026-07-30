import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MultiVectorPage from "./page";

describe("MultiVectorPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the experimental source controls", () => {
    render(<MultiVectorPage />);

    expect(screen.getByRole("heading", { name: /multi-vector drawing index/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Project ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Source ID")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enable" })).toBeDisabled();
  });

  it("loads project sources and selects one", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: "project:test",
        sources: [
          {
            project_id: "project:test",
            source_id: "source:test",
            source_title: "Architectural Plans",
            enabled: false,
            status: "disabled",
            persisted_status: "disabled",
            stale: false,
            point_count: 0,
          },
        ],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MultiVectorPage />);
    fireEvent.change(screen.getByLabelText("Project ID"), {
      target: { value: "project:test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load project sources" }));

    const sourceButton = await screen.findByRole("button", { name: /Architectural Plans/i });
    fireEvent.click(sourceButton);

    expect(screen.getByLabelText("Source ID")).toHaveValue("source:test");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/drawing-extractions/multivector/projects/project%3Atest/sources",
    );
  });

  it("loads and displays live source status", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: "project:test",
        source_id: "source:test",
        source_title: "Architectural Plans",
        enabled: true,
        status: "ready",
        persisted_status: "ready",
        stale: false,
        point_count: 14,
        qdrant_available: true,
        current_file_hash: "current",
        indexed_file_hash: "current",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MultiVectorPage />);
    fireEvent.change(screen.getByLabelText("Project ID"), {
      target: { value: "project:test" },
    });
    fireEvent.change(screen.getByLabelText("Source ID"), {
      target: { value: "source:test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load status" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Ready" })).toBeInTheDocument());
    expect(screen.getByText("Architectural Plans")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/drawing-extractions/multivector/projects/project%3Atest/sources/source%3Atest",
      { method: "GET" },
    );
  });

  it("posts the enable action", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: "project:test",
        source_id: "source:test",
        enabled: true,
        status: "not_indexed",
        persisted_status: "not_indexed",
        stale: false,
        point_count: 0,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MultiVectorPage />);
    fireEvent.change(screen.getByLabelText("Project ID"), {
      target: { value: "project:test" },
    });
    fireEvent.change(screen.getByLabelText("Source ID"), {
      target: { value: "source:test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enable" }));

    await waitFor(() => expect(screen.getByText("Enable completed.")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/drawing-extractions/multivector/projects/project%3Atest/sources/source%3Atest/enable",
      { method: "POST" },
    );
  });
});
