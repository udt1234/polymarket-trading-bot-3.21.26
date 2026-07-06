import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        term: {
          bg: "#0a0e14",
          panel: "#10151d",
          border: "#1c2432",
          text: "#c9d4e3",
          muted: "#5c6b82",
          green: "#22c55e",
          red: "#ef4444",
          amber: "#f59e0b",
          accent: "#38bdf8",
        },
      },
      fontFamily: {
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
