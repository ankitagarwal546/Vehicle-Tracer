/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F8FAFC",
        line: "#E2E8F0",
        ink: "#0F172A",
        muted: "#475569",
        navy: { DEFAULT: "#1E3A5F", dark: "#172D4A", tint: "#EAF0F7" },
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "Menlo", "Consolas", "monospace"],
      },
      fontSize: { "2xs": ["11px", "15px"] },
    },
  },
  plugins: [],
};
