import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Outrun palette - deep darks with neon accents
        slate: {
          950: "#0a0612", // Deep purple-black
          900: "#0f0a18", // Dark purple
          850: "#150d20", // Purple undertone
          800: "#1a0a2e", // Mountain purple (from logo)
          750: "#251538",
          700: "#2d1d42",
        },
        // Primary accent - hot pink/magenta (grid lines from logo)
        outrun: {
          50: "#fff0f6",
          100: "#ffe0ed",
          200: "#ffc2db",
          300: "#ff8fbd",
          400: "#ff5c9d",
          500: "#ff0066", // Primary - grid pink
          600: "#e6005c",
          700: "#cc0052",
          800: "#a30042",
          900: "#800033",
        },
        // Sunset gradient colors
        sunset: {
          yellow: "#fff200",
          orange: "#ff6600",
          pink: "#ff0066",
        },
        // Keep some utility colors
        amber: {
          400: "#fbbf24",
          500: "#f59e0b",
        },
        rose: {
          400: "#fb7185",
          500: "#f43f5e",
        },
        // Cyan accent for contrast
        neon: {
          cyan: "#00f5ff",
          purple: "#bf00ff",
        },
        // Phosphor - neon cyan accent scale
        phosphor: {
          400: "#33f7ff", // Lighter cyan
          500: "#00f5ff", // Base neon cyan
          600: "#00d4dd", // Darker cyan
          700: "#00b3bb", // Darkest cyan
        },
        // Semantic priority colors
        priority: {
          critical: "#ff0066", // outrun-500
          high: "#ff6600", // sunset-orange
          medium: "#f59e0b", // amber-500
          low: "#64748b", // slate-500
        },
        // Semantic status colors
        status: {
          success: "#00f5ff", // phosphor-500
          warning: "#f59e0b", // amber-500
          error: "#f43f5e", // rose-500
          info: "#3b82f6", // blue-500
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', "monospace"],
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        body: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }], // 10px text
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "scan": "scan 8s linear infinite",
        "glow": "glow 2s ease-in-out infinite alternate",
        "fade-in": "fadeIn 0.5s ease-out",
        "slide-up": "slideUp 0.5s ease-out",
        "grid-scroll": "gridScroll 20s linear infinite",
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
        gridScroll: {
          "0%": { transform: "translateY(0)" },
          "100%": { transform: "translateY(32px)" },
        },
      },
      backgroundImage: {
        "grid-pattern": `linear-gradient(to right, rgba(255, 0, 102, 0.15) 1px, transparent 1px),
                         linear-gradient(to bottom, rgba(255, 0, 102, 0.15) 1px, transparent 1px)`,
        "scanline": "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px)",
        "sunset-gradient": "linear-gradient(180deg, #fff200 0%, #ff6600 50%, #ff0066 100%)",
      },
      backgroundSize: {
        "grid": "24px 24px",
      },
      boxShadow: {
        "outrun": "0 0 20px rgba(255, 0, 102, 0.3), 0 0 40px rgba(255, 0, 102, 0.1)",
        "outrun-sm": "0 0 10px rgba(255, 0, 102, 0.25)",
        "outrun-lg": "0 0 30px rgba(255, 0, 102, 0.4), 0 0 60px rgba(255, 0, 102, 0.2)",
        "sunset": "0 0 20px rgba(255, 102, 0, 0.3), 0 0 40px rgba(255, 0, 102, 0.2)",
      },
    },
  },
  plugins: [],
};

export default config;
