import type { Config } from "tailwindcss";

// Assay-lab palette: shale ground, core-tray surfaces, assay-gold accent,
// oxide teal for constructive states, hazard red for D/F risk.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        shale: "#101312",
        tray: "#1A1E1C",
        seam: "#2A302D",
        bone: "#E9E4D8",
        ash: "#8D958F",
        assay: "#E8B44A",
        oxide: "#58B09C",
        hazard: "#D4574E",
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
