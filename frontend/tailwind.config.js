const { heroui } = require("@heroui/react");

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./node_modules/@heroui/theme/dist/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Poppins', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      colors: {
        // Keep Tailwind colors for non-HeroUI components
        primary: {
          50: '#e8f0fe',
          100: '#d2e3fc',
          200: '#aecbfa',
          300: '#8ab4f8',
          400: '#669df6',
          500: '#4285f4',
          600: '#1a73e8',
          700: '#1967d2',
          800: '#185abc',
          900: '#174ea6',
        },
      },
    },
  },
  darkMode: "class",
  plugins: [
    heroui({
      addCommonColors: true,
      themes: {
        light: {
          colors: {
            // Google Blue - Primary color (Pixel style)
            primary: {
              50: '#e8f0fe',
              100: '#d2e3fc',
              200: '#aecbfa',
              300: '#8ab4f8',
              400: '#669df6',
              500: '#4285f4',
              600: '#1a73e8',
              700: '#1967d2',
              800: '#185abc',
              900: '#174ea6',
              DEFAULT: '#1a73e8',
              foreground: '#ffffff',
            },
            // Google Green - Success
            success: {
              50: '#e6f4ea',
              100: '#ceead6',
              200: '#a8dab5',
              300: '#81c995',
              400: '#5bb974',
              500: '#34a853',
              600: '#1e8e3e',
              700: '#188038',
              800: '#137333',
              900: '#0d652d',
              DEFAULT: '#34a853',
              foreground: '#ffffff',
            },
            // Google Red - Danger
            danger: {
              50: '#fce8e6',
              100: '#fad2cf',
              200: '#f6aea9',
              300: '#f28b82',
              400: '#ee675c',
              500: '#ea4335',
              600: '#d93025',
              700: '#c5221f',
              800: '#b31412',
              900: '#a50e0e',
              DEFAULT: '#ea4335',
              foreground: '#ffffff',
            },
            // Google Yellow - Warning
            warning: {
              50: '#fef7e0',
              100: '#feefc3',
              200: '#fde293',
              300: '#fdd663',
              400: '#fcc934',
              500: '#fbbc04',
              600: '#f9ab00',
              700: '#f29900',
              800: '#ea8600',
              900: '#e37400',
              DEFAULT: '#fbbc04',
              foreground: '#000000',
            },
            // Neutral grays
            default: {
              50: '#f8f9fa',
              100: '#f1f3f4',
              200: '#e8eaed',
              300: '#dadce0',
              400: '#bdc1c6',
              500: '#9aa0a6',
              600: '#80868b',
              700: '#5f6368',
              800: '#3c4043',
              900: '#202124',
              DEFAULT: '#5f6368',
              foreground: '#ffffff',
            },
            background: '#ffffff',
            foreground: '#202124',
            focus: '#1a73e8',
          },
        },
      },
    }),
  ],
}

