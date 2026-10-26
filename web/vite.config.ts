import { defineConfig } from 'vite';
// Dev server must also serve ../schemas (validated at import time) and ../data/fake (dev-only fallback fetch).
export default defineConfig({ base: './', server: { fs: { allow: ['..'] } } });
