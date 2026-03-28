/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        border: "hsl(var(--border))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        category: {
          finance: "#10b981",
          tech: "#3b82f6",
          politics: "#ef4444",
          entertainment: "#f59e0b",
          gaming: "#8b5cf6",
          sports: "#06b6d4",
          world: "#6366f1",
          science: "#14b8a6",
          health: "#ec4899",
          other: "#6b7280",
        },
        sentiment: {
          positive: "#10b981",
          neutral: "#6b7280",
          negative: "#ef4444",
        },
      },
      keyframes: {
        'toast-slide-in': {
          from: { transform: 'translateX(100%)', opacity: '0' },
          to: { transform: 'translateX(0)', opacity: '1' },
        },
        'toast-slide-out': {
          from: { transform: 'translateX(0)', opacity: '1' },
          to: { transform: 'translateX(100%)', opacity: '0' },
        },
      },
      animation: {
        'toast-in': 'toast-slide-in 200ms ease-out',
        'toast-out': 'toast-slide-out 150ms ease-in forwards',
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
