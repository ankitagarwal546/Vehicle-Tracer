import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { CaseDetail, CaseSummary, PlateFormat, RegistrySnapshot } from "../types";

export type RegistryCoverageData = RegistrySnapshot & {
  formats: { plate_format: PlateFormat; label: string; compatible_records: number }[];
};

export interface Overview {
  details: CaseDetail[];
  failed: string[];
  coverage: RegistryCoverageData | null;
  coverageFailed: boolean;
  loading: boolean;
}

const CONCURRENT_REQUESTS = 4;

/** Loads case details with bounded concurrency. One failed case never hides the others. */
export function useOverview(cases: CaseSummary[], enabled: boolean, registryVersion: number): Overview {
  const [state, setState] = useState<Overview>({ details: [], failed: [], coverage: null, coverageFailed: false, loading: true });
  const request = useRef(0);
  const key = cases.map((item) => `${item.id}:${item.status}:${item.updated_at}:${item.vehicle_count}:${item.clip_count}`).join("|");

  useEffect(() => {
    if (!enabled) return;
    const id = ++request.current;
    let cursor = 0;
    const details: CaseDetail[] = [];
    const failed: string[] = [];
    const worker = async () => {
      while (cursor < cases.length) {
        const item = cases[cursor++];
        try {
          details.push(await api.getCase(item.id));
        } catch {
          failed.push(item.title);
        }
      }
    };
    const order = new Map(cases.map((item, index) => [item.id, index]));
    void Promise.all([
      Promise.all(Array.from({ length: Math.min(CONCURRENT_REQUESTS, cases.length) }, worker)),
      api.registryCoverage().then((coverage) => coverage).catch(() => null),
    ]).then(([, coverage]) => {
      if (id !== request.current) return;
      details.sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
      setState({ details, failed, coverage, coverageFailed: coverage === null, loading: false });
    });
    // `key` captures every list change that can alter these figures.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, registryVersion]);

  return state;
}
