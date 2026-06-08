export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        base:     '#0d0f1a',
        card:     '#13162a',
        sidebar:  '#0a0c18',
        input:    '#1c2038',
        border:   '#2a2f52',
        accent:   '#6366f1',
        'accent-dark': '#4f46e5',
        muted:    '#4a5580',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      }
    }
  },
  plugins: []
}
