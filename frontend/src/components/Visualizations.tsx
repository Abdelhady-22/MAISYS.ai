// Renders the appropriate visualization based on the orchestrator's
// `visual_type` hint. Each visual is intentionally minimal — a real
// product would use a charting library for pk_curve and a more
// elaborate flowchart component for dosing_flowchart.

import { useTranslation } from "react-i18next";

import type {
  ComparisonData,
  DosageData,
  InteractionsData,
  Language,
  LookupData,
  PKData,
  QueryResponse,
  Severity,
} from "../types/api";

interface Props {
  response: QueryResponse;
  language: Language;
}

const SEVERITY_BG: Record<Severity, string> = {
  minor: "bg-severity-minor",
  moderate: "bg-severity-moderate",
  major: "bg-severity-major",
  contraindicated: "bg-severity-contraindicated",
};

const SEVERITY_WIDTH: Record<Severity, string> = {
  minor: "w-1/4",
  moderate: "w-2/4",
  major: "w-3/4",
  contraindicated: "w-full",
};

export function Visualizations({ response, language }: Props) {
  switch (response.visual_type) {
    case "severity_bar":
      return <SeverityBar data={response.data as unknown as InteractionsData} language={language} />;
    case "comparison_table":
      return <ComparisonTable data={response.data as unknown as ComparisonData} language={language} />;
    case "dosing_flowchart":
      return <DosingFlowchart data={response.data as unknown as DosageData} language={language} />;
    case "pk_curve":
      return <PKCurve data={response.data as unknown as PKData} language={language} />;
    case "card":
    default:
      return <GenericCard data={response.data} language={language} />;
  }
}

function SeverityBar({ data, language }: { data: InteractionsData; language: Language }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      {data.overall_severity ? (
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">{t("labels.severity")}:</span>
          <div className="flex-1 bg-slate-200 h-4 rounded overflow-hidden">
            <div className={`h-full ${SEVERITY_BG[data.overall_severity]} ${SEVERITY_WIDTH[data.overall_severity]}`} />
          </div>
          <span className="text-sm">{t(`severity.${data.overall_severity}`)}</span>
        </div>
      ) : null}
      {data.pairs.map((pair, i) => (
        <div key={i} className="border rounded p-3 bg-white">
          <div className="flex justify-between items-start gap-3">
            <div className="font-medium">
              {pair.drug_a} <span className="text-slate-400">↔</span> {pair.drug_b}
            </div>
            <span
              className={`text-xs px-2 py-1 rounded text-white ${SEVERITY_BG[pair.severity]}`}
            >
              {t(`severity.${pair.severity}`)}
            </span>
          </div>
          <p className="text-sm mt-2 text-slate-700">{pair.description[language]}</p>
          <p className="text-xs text-slate-400 mt-1">source: {pair.source_tier}</p>
        </div>
      ))}
    </div>
  );
}

function ComparisonTable({ data, language }: { data: ComparisonData; language: Language }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-100">
          <tr>
            <th className="px-3 py-2 text-start">{t("labels.generic")}</th>
            <th className="px-3 py-2 text-start">{t("labels.class")}</th>
            <th className="px-3 py-2 text-start">{t("labels.mechanism")}</th>
            <th className="px-3 py-2 text-start">Cost</th>
            <th className="px-3 py-2 text-start">{t("labels.contraindications")}</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.drug_rxcui} className="border-b">
              <td className="px-3 py-2 font-medium">{row.drug_name}</td>
              <td className="px-3 py-2">{row.drug_class ?? "—"}</td>
              <td className="px-3 py-2">{row.mechanism[language]}</td>
              <td className="px-3 py-2">{row.cost_tier}</td>
              <td className="px-3 py-2">
                <ul className="list-disc list-inside">
                  {row.contraindications.map((c, i) => (
                    <li key={i}>{c[language]}</li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DosingFlowchart({ data, language }: { data: DosageData; language: Language }) {
  return (
    <div className="space-y-3">
      {data.regimens.map((r, i) => (
        <div key={i} className="border-s-4 border-blue-500 ps-3 py-1">
          <div className="text-xs uppercase tracking-wide text-blue-600">{r.population}</div>
          <div className="font-medium">{r.standard_dose[language]}</div>
          {r.max_daily ? (
            <div className="text-sm text-slate-600">max: {r.max_daily[language]}</div>
          ) : null}
          {r.notes ? <div className="text-xs text-slate-500 mt-1">{r.notes[language]}</div> : null}
        </div>
      ))}
      {data.adjustments_applied.length > 0 ? (
        <div className="text-sm bg-amber-50 border border-amber-200 rounded p-3">
          <div className="font-medium text-amber-800 mb-1">Adjustments applied:</div>
          <ul className="list-disc list-inside text-amber-900">
            {data.adjustments_applied.map((a, i) => (
              <li key={i}>{a[language]}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function PKCurve({ data, language }: { data: PKData; language: Language }) {
  // Real PK curve would render a chart. This is a minimal labelled
  // summary that still gives the user the key numbers.
  return (
    <div className="grid grid-cols-2 gap-3 text-sm">
      <Cell label="Tmax (h)" value={data.absorption.tmax_hours} />
      <Cell label="Bioavailability (%)" value={data.absorption.bioavailability_percent} />
      <Cell label="Vd (L/kg)" value={data.distribution.vd_l_per_kg} />
      <Cell label="Protein binding (%)" value={data.distribution.protein_binding_percent} />
      <Cell label="Primary CYP" value={data.metabolism.primary_cyp_enzymes.join(", ") || "—"} />
      <Cell label="Half-life (h)" value={data.excretion.half_life_hours} />
      <Cell label="Primary route" value={data.excretion.primary_route ?? "—"} />
      {data.metabolism.notes ? (
        <div className="col-span-2 text-xs text-slate-600 mt-2">
          {data.metabolism.notes[language]}
        </div>
      ) : null}
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="border rounded p-2 bg-white">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-medium">{value ?? "—"}</div>
    </div>
  );
}

function GenericCard({ data, language }: { data: Record<string, unknown>; language: Language }) {
  // Best-effort render for lookup / alternative / acquisition.
  // Each agent has different shape; we surface the obvious fields.
  const lookup = data as Partial<LookupData>;
  if (lookup.generic_name) {
    return (
      <div className="space-y-2">
        <div className="text-xl font-medium">{lookup.generic_name}</div>
        {lookup.brand_names && lookup.brand_names.length > 0 ? (
          <div className="text-sm text-slate-600">brands: {lookup.brand_names.join(", ")}</div>
        ) : null}
        {lookup.drug_class ? (
          <div className="text-sm text-slate-600">class: {lookup.drug_class}</div>
        ) : null}
        {lookup.indications && lookup.indications.length > 0 ? (
          <div>
            <div className="text-sm font-medium mt-3">Indications:</div>
            <ul className="list-disc list-inside text-sm">
              {lookup.indications.map((i, idx) => (
                <li key={idx}>{i[language]}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {lookup.mechanism_of_action ? (
          <div className="text-sm mt-2 italic">{lookup.mechanism_of_action[language]}</div>
        ) : null}
      </div>
    );
  }
  // Fallback: raw JSON dump
  return (
    <pre className="text-xs bg-slate-100 p-3 rounded overflow-x-auto">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
