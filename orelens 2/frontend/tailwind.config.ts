import type { Config } from "tailwindcss";

// Platinum palette: silver-white ground, white surfaces, royal-blue accent,
// emerald for constructive states, crimson for D/F risk. Light theme.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        shale: "#F4F7FC",
        tray: "#FFFFFF",
        seam: "#CFD9E8",
        bone: "#0E1E3C",
        ash: "#5C6B85",
        assay: "#1E4FD8",
        oxide: "#0B8F63",
        hazard: "#C42B2B",
        silver: "#E3E9F3",
        steel: "#8FA0BC",
        royal: "#1E4FD8",
        royalDeep: "#0F2E9E",
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
