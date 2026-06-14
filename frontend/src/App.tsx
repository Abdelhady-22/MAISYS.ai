import { useState } from "react";
import { useTranslation } from "react-i18next";

import { generateJobId, submitQuery, subscribeProgress } from "./api/client";
import { Visualizations } from "./components/Visualizations";
import type { Language, ProgressEvent, QueryResponse } from "./types/api";

export function App() {
  const { t, i18n } = useTranslation();
  const language = i18n.language as Language;

  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [progressEvents, setProgressEvents] = useState<ProgressEvent[]>([]);
  const [response, setResponse] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!text.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    setResponse(null);
    setProgressEvents([]);

    const jobId = generateJobId();
    let unsubscribe = () => {};
    try {
      // Subscribe to progress BEFORE making the POST request,
      // so events arriving during dispatch aren't missed.
      unsubscribe = subscribeProgress(
        jobId,
        (event) => setProgressEvents((prev) => [...prev, event]),
        () => {},
      );

      const result = await submitQuery({
        text,
        language,
        job_id: jobId,
      });
      setResponse(result);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "unknown error");
    } finally {
      setSubmitting(false);
      // Close the WS after the POST returns. Progress events should
      // have completed by now since the orchestrator publishes
      // before each step.
      setTimeout(unsubscribe, 500);
    }
  }

  return (
    <div className="min-h-screen p-4 sm:p-8 max-w-4xl mx-auto">
      <header className="flex justify-between items-center mb-8">
        <h1 className="text-2xl font-bold">{t("appTitle")}</h1>
        <LanguageSwitcher />
      </header>

      <div className="bg-white border rounded p-4 space-y-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("queryPlaceholder") ?? ""}
          rows={3}
          className="w-full border rounded p-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          dir={language === "ar" ? "rtl" : "ltr"}
        />
        <button
          onClick={handleSubmit}
          disabled={submitting || !text.trim()}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-400 text-white px-4 py-2 rounded"
        >
          {submitting ? t("submitting") : t("submit")}
        </button>
      </div>

      {error ? (
        <div className="mt-4 bg-red-50 border border-red-200 text-red-800 p-3 rounded">{error}</div>
      ) : null}

      {progressEvents.length > 0 ? (
        <section className="mt-6">
          <h2 className="text-sm uppercase tracking-wide text-slate-500 mb-2">
            {t("sections.progress")}
          </h2>
          <ol className="bg-white border rounded divide-y">
            {progressEvents.map((event, i) => (
              <li key={i} className="px-3 py-2 text-sm flex items-center gap-3">
                <ProgressDot status={event.status} />
                <span>{event.message}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {response ? <ResultSection response={response} language={language} /> : null}
    </div>
  );
}

function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  return (
    <div className="flex gap-1 text-sm">
      <button
        onClick={() => i18n.changeLanguage("en")}
        className={`px-3 py-1 rounded ${i18n.language === "en" ? "bg-blue-600 text-white" : "bg-slate-200"}`}
      >
        {t("english")}
      </button>
      <button
        onClick={() => i18n.changeLanguage("ar")}
        className={`px-3 py-1 rounded ${i18n.language === "ar" ? "bg-blue-600 text-white" : "bg-slate-200"}`}
      >
        {t("arabic")}
      </button>
    </div>
  );
}

function ProgressDot({ status }: { status: ProgressEvent["status"] }) {
  const color =
    status === "completed"
      ? "bg-emerald-500"
      : status === "failed"
        ? "bg-red-500"
        : "bg-blue-500 animate-pulse";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}

function ResultSection({ response, language }: { response: QueryResponse; language: Language }) {
  const { t } = useTranslation();
  return (
    <section className="mt-6 space-y-4">
      <h2 className="text-sm uppercase tracking-wide text-slate-500">{t("sections.result")}</h2>

      <div className="bg-white border rounded p-4">
        <div className="text-xs text-slate-500 mb-3 flex gap-4">
          <span>
            {t("labels.agent")}: <strong>{response.meta.agent_name}</strong>
          </span>
          <span>
            {t("labels.confidence")}: <strong>{(response.meta.confidence * 100).toFixed(0)}%</strong>
          </span>
          <span>
            {t("labels.latency")}: <strong>{response.meta.latency_ms}ms</strong>
          </span>
        </div>
        <Visualizations response={response} language={language} />
      </div>

      {response.citations.length > 0 ? (
        <details className="bg-white border rounded p-3">
          <summary className="cursor-pointer text-sm font-medium">{t("sections.citations")}</summary>
          <ul className="mt-2 text-xs space-y-1">
            {response.citations.map((c, i) => (
              <li key={i} className="text-slate-600">
                <span className="font-medium">[{c.source}]</span> {c.title ?? c.snippet?.slice(0, 60)}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <div className="bg-amber-50 border border-amber-200 rounded p-3 text-xs">
        <div className="font-medium text-amber-900 mb-1">{t("sections.disclaimer")}</div>
        <div className="text-amber-800">{response.meta.disclaimer[language]}</div>
      </div>
    </section>
  );
}
