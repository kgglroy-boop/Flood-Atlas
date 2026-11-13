import { createLogger, defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import {resolve} from 'node:path';

const logger = createLogger();
const logError = logger.error.bind(logger);
logger.error = (message, options) => {
  // Vite's default proxy diagnostic embeds the raw URL and upstream error.
  // Keep unrelated compiler diagnostics, but never log API query payloads.
  if (message.includes('http proxy error:') || message.includes('ws proxy error:') || message.includes('ws proxy socket error:')) {
    logError('API proxy unavailable', { timestamp: true });
    return;
  }
  logError(message, options);
};

export default defineConfig({
  customLogger: logger,
  plugins: [vue()],
  build:{rolldownOptions:{input:{
    main:resolve(import.meta.dirname,'index.html'),
    legacy:resolve(import.meta.dirname,'legacy.html'),
    legacyMvt:resolve(import.meta.dirname,'legacy-mvt.html'),
    mvt:resolve(import.meta.dirname,'mvt-demo.html'),
  }}},
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET ?? 'http://backend:8000',
        changeOrigin: true,
      },
      '^/geoserver/gwc/service/wmts(?:\\?|$)': {
        target: process.env.GEOSERVER_PROXY_TARGET ?? 'http://geoserver:8080',
        changeOrigin: true,
      },
    },
  },
});
