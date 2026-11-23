/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#100C20",
        surface: "#18132C",
        raised: "#211B3A",
        line: "#2F2850",
        ink: "#F3F1FB",
        muted: "#ABA6C4",
        signal: "#F6D743",
        shell: { DEFAULT: "#0C0919", raised: "#1D1836", line: "#2A2447", text: "#ECEAF7", muted: "#A9A4C2" },
        accent: { DEFAULT: "#6A53E6", dark: "#5742CC", tint: "#272048", line: "#4B3F8C", soft: "#C4BAFF" },
        // Status ramps are inverted so existing status classes read correctly on dark panels.
        amber: { 50: "#2A2113", 100: "#3B2D12", 200: "#5A4413", 300: "#7A5D19", 400: "#A67C1F", 500: "#D9A425", 700: "#FBBF24", 800: "#FCD34D", 900: "#FDE68A", 950: "#FEF3C7" },
        rose: { 50: "#2E1522", 100: "#431B2C", 200: "#5E2338", 300: "#83304C", 700: "#FB7185", 800: "#FDA4AF", 900: "#FECDD3", 950: "#FFE4E6" },
        emerald: { 50: "#0F2A23", 100: "#123B2E", 200: "#175340", 300: "#1F7558", 800: "#6EE7B7", 900: "#A7F3D0", 950: "#D1FAE5" },
        slate: { 100: "#251F3E", 300: "#3F385E", 400: "#5D5680", 500: "#9791B3" },
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "Menlo", "Consolas", "monospace"],
      },
      fontSize: { "2xs": ["11px", "15px"] },
      borderRadius: { evidence: "8px" },
    },
  },
  plugins: [],
};
