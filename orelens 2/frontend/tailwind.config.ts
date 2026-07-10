import type { Config } from "tailwindcss";

// Assay-lab palette: shale ground, core-tray surfaces, assay-gold accent,
// oxide teal for constructive states, hazard red for D/F risk.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        shale: "#131110",
        tray: "#1D1915",
        seam: "#332D25",
        bone: "#F1EADB",
        ash: "#A79E8F",
        assay: "#E3B356",
        oxide: "#5FBCA4",
        hazard: "#DD5F55",
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
