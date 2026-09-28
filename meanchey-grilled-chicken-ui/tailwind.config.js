import colors from 'tailwindcss/colors'

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Kantumruy Pro"', '"Noto Sans Khmer"', 'system-ui', 'sans-serif'],
      },
      colors: {
        brand: colors.orange,
      },
    },
  },
  plugins: [],
}
