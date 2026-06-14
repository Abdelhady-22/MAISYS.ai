/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        severity: {
          minor: "#10b981",
          moderate: "#f59e0b",
          major: "#ef4444",
          contraindicated: "#7f1d1d",
        },
      },
      fontFamily: {
        ar: ['"Noto Sans Arabic"', "sans-serif"],
      },
    },
  },
  plugins: [],
};
