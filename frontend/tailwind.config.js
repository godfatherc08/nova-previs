/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        black: "var(--black)",
        "film-base": "var(--film-base)",
        graphite: "var(--graphite)",
        silver: "var(--silver)",
        light: "var(--light)",
        key: "var(--key)",
        leader: "var(--leader-amber)",
        border: "var(--graphite)",
        input: "var(--graphite)",
        ring: "var(--silver)",
        background: "var(--black)",
        foreground: "var(--light)",
        primary: {
          DEFAULT: "var(--light)",
          foreground: "var(--black)",
        },
        secondary: {
          DEFAULT: "var(--film-base)",
          foreground: "var(--light)",
        },
        muted: {
          DEFAULT: "var(--film-base)",
          foreground: "var(--silver)",
        },
        accent: {
          DEFAULT: "var(--film-base)",
          foreground: "var(--light)",
        },
        destructive: {
          DEFAULT: "var(--graphite)",
          foreground: "var(--light)",
        },
        card: {
          DEFAULT: "var(--film-base)",
          foreground: "var(--light)",
        },
        popover: {
          DEFAULT: "var(--film-base)",
          foreground: "var(--light)",
        },
      },
      fontFamily: {
        display: ["Anton", "Archivo Black", "sans-serif"],
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      animation: {
        "grain-shift": "grain-shift 8s steps(10) infinite",
        "leader-spin": "leader-spin 1.2s linear infinite",
      },
      keyframes: {
        "grain-shift": {
          "0%, 100%": { transform: "translate(0, 0)" },
          "10%": { transform: "translate(-2%, -3%)" },
          "30%": { transform: "translate(3%, 2%)" },
          "50%": { transform: "translate(-1%, 4%)" },
          "70%": { transform: "translate(4%, -1%)" },
          "90%": { transform: "translate(-3%, 1%)" },
        },
        "leader-spin": {
          from: { transform: "rotate(0deg)" },
          to: { transform: "rotate(360deg)" },
        },
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
