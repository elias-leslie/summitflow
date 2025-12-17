import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Core palette - deep slate with phosphor green
        slate: {
          950: "#0a0c0f",
          900: "#0f1115",
          850: "#14171c",
          800: "#1a1e24",
          750: "#21262d",
          700: "#2d333b",
        },
        phosphor: {
          50: "#e8fff0",
          100: "#c5ffda",
          200: "#8bfbb5",
          300: "#4ef28e",
          400: "#22e06a",
          500: "#00c853", // Primary
          600: "#00a344",
          700: "#007d35",
          800: "#00612a",
          900: "#004d22",
        },
        amber: {
          400: "#fbbf24",
          500: "#f59e0b",
        },
        rose: {
          400: "#fb7185",
          500: "#f43f5e",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', "monospace"],
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        body: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "scan": "scan 8s linear infinite",
        "glow": "glow 2s ease-in-out infinite alternate",
        "fade-in": "fadeIn 0.5s ease-out",
        "slide-up": "slideUp 0.5s ease-out",
      },
      keyframes: {
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100vh)" },
        },
        glow: {
          "0%": { opacity: "0.5" },
          "100%": { opacity: "1" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      backgroundImage: {
        "grid-pattern": `linear-gradient(to right, rgba(45, 51, 59, 0.3) 1px, transparent 1px),
                         linear-gradient(to bottom, rgba(45, 51, 59, 0.3) 1px, transparent 1px)`,
        "scanline": "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px)",
      },
      backgroundSize: {
        "grid": "24px 24px",
      },
    },
  },
  plugins: [],
};

export default config;
