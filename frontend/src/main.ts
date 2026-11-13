import {createApp} from 'vue';
import {setWorkerUrl} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';

setWorkerUrl(workerUrl);
if (location.pathname.endsWith('/legacy.html')) {
  void Promise.all([import('./App.vue'),import('./style.css')]).then(([page])=>createApp(page.default).mount('#app'));
} else {
  void Promise.all([import('./AtlasApp.vue'),import('./atlas.css')]).then(([page])=>createApp(page.default).mount('#app'));
}
