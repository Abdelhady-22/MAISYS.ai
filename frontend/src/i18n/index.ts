// i18n bootstrap with EN + AR. The HTML `dir` attribute is updated
// on language change so RTL flips for Arabic without per-component
// `dir` plumbing.

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

const resources = {
  en: {
    translation: {
      appTitle: "MAISYS Drug Information",
      queryPlaceholder: "Ask a question about a drug…",
      submit: "Ask",
      submitting: "Working…",
      language: "Language",
      english: "English",
      arabic: "العربية",
      sections: {
        progress: "Progress",
        result: "Result",
        citations: "Citations",
        disclaimer: "Disclaimer",
      },
      labels: {
        confidence: "Confidence",
        agent: "Agent",
        latency: "Latency",
        rxcui: "RxCUI",
        generic: "Generic name",
        brands: "Brand names",
        class: "Drug class",
        indications: "Indications",
        mechanism: "Mechanism of action",
        contraindications: "Contraindications",
        severity: "Severity",
      },
      severity: {
        minor: "Minor",
        moderate: "Moderate",
        major: "Major",
        contraindicated: "Contraindicated",
      },
      errors: {
        loginRequired: "Please log in before submitting a query.",
        queryFailed: "The query failed. Please try again.",
      },
    },
  },
  ar: {
    translation: {
      appTitle: "MAISYS — معلومات الأدوية",
      queryPlaceholder: "اسأل سؤالاً عن دواء…",
      submit: "اسأل",
      submitting: "جاري المعالجة…",
      language: "اللغة",
      english: "English",
      arabic: "العربية",
      sections: {
        progress: "التقدم",
        result: "النتيجة",
        citations: "المصادر",
        disclaimer: "إخلاء المسؤولية",
      },
      labels: {
        confidence: "الثقة",
        agent: "العميل",
        latency: "زمن الاستجابة",
        rxcui: "RxCUI",
        generic: "الاسم العلمي",
        brands: "الأسماء التجارية",
        class: "الفئة الدوائية",
        indications: "الاستخدامات",
        mechanism: "آلية العمل",
        contraindications: "موانع الاستعمال",
        severity: "الشدة",
      },
      severity: {
        minor: "طفيف",
        moderate: "متوسط",
        major: "خطير",
        contraindicated: "ممنوع",
      },
      errors: {
        loginRequired: "يرجى تسجيل الدخول قبل إرسال الاستعلام.",
        queryFailed: "فشل الاستعلام. يرجى المحاولة مرة أخرى.",
      },
    },
  },
};

i18n.use(initReactI18next).init({
  resources,
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
  document.documentElement.dir = lng === "ar" ? "rtl" : "ltr";
});

export default i18n;
