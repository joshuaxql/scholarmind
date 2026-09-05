"use client";

import { useCallback, useEffect, useState } from "react";
import { getPaper } from "@/lib/api";
import type { Paper } from "@/types/api";

const ACTIVE_STATUSES = new Set(["queued", "downloading", "parsing", "indexing"]);

export function usePaper(paperId: string) {
  const [paper, setPaper] = useState<Paper | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    try {
      const next = await getPaper(paperId);
      setPaper(next);
      setError(null);
      setLoading(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load this paper");
      setLoading(false);
    }
  }, [paperId]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (!paper || !ACTIVE_STATUSES.has(paper.status)) return;
    const timer = setTimeout(() => void load(), 1500);
    return () => clearTimeout(timer);
  }, [load, paper]);

  return { paper, error, loading, refresh: load };
}
