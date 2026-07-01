import type { Config } from "tailwindcss";

// White-gloss palette: bright surfaces, grey body text, blue accent.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        shale: "#F5F7FA",
        tray: "#FFFFFF",
        seam: "#DDE3EA",
        bone: "#3A4452",
        ash: "#8A94A4",
        assay: "#2563EB",
        oxide: "#0E9F6E",
        hazard: "#DC2626",
      },
      fontFamily: {
        display: ["'Barlow Condensed'", "ui-sans-serif", "sans-serif"],
        body: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
