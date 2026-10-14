import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  resolve: {
    alias: {
      // Absolute imports from the source root: `@/context/theme` instead of
      // `../../../context/theme`. Moving a file then never means rewriting
      // its imports, and a reader can tell where something lives from the
      // import line alone.
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    port: 5173, // one of the origins model/api.py allows through CORS
    open: true,
  },
});
