import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

/* The one and only global stylesheet import. It declares the cascade layers
   the whole app depends on, so it must land before any component CSS. */
import '@/styles/index.css';

import { AuthProvider } from '@/context/auth';
import { ThemeProvider } from '@/context/theme';

import App from '@/App';

/* Provider order matters in one direction only: the theme is available to the
   auth screens (they carry the theme switcher), and nothing in the theme
   layer needs to know who is signed in. So the theme goes outside. */
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
);
