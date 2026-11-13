<script setup lang="ts">
defineProps<{ name: string; size?: number }>();
</script>

<template>
  <svg :width="size ?? 20" :height="size ?? 20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path v-if="name === 'mark'" d="M3 8.4 12 3l9 5.4-9 5.3-9-5.3Zm0 5.2 9 5.4 9-5.4M3 18.6l9 5.4 9-5.4" transform="translate(0,-1) scale(1,.95)" />
    <template v-else-if="name === 'search'"><circle cx="10.8" cy="10.8" r="5.8" /><path d="m15.2 15.2 4 4" /></template>
    <path v-else-if="name === 'folder'" d="M3.5 6.5h6.4l2 2.3h8.6v9.7h-17v-12Z" />
    <path v-else-if="name === 'image'" d="M3.5 5.5h17v13h-17zM4 15l4.5-4.5 3.5 3.5 2.5-2.5 5.5 5.5M15.8 9h.1" />
    <path v-else-if="name === 'layers'" d="m3 8 9-5 9 5-9 5-9-5Zm0 4.5 9 5 9-5M3 17l9 5 9-5" />
    <path v-else-if="name === 'compare'" d="M10 4h-6v16h6m4-16h6v16h-6m-2-18v20M9.5 9.5 7 12l2.5 2.5m5-5L17 12l-2.5 2.5" />
    <path v-else-if="name === 'swipe'" d="m9 8-4 4 4 4m6-8 4 4-4 4" />
    <path v-else-if="name === 'plus'" d="M12 5v14M5 12h14" />
    <path v-else-if="name === 'minus'" d="M5 12h14" />
    <path v-else-if="name === 'compass'" d="m12 3 6 17-6-4-6 4 6-17Z" />
    <template v-else-if="name === 'target'"><circle cx="12" cy="12" r="6.5" /><circle cx="12" cy="12" r="1" /><path d="M12 2.5v3m0 13v3m9.5-9.5h-3m-13 0h-3" /></template>
    <path v-else-if="name === 'drop'" d="M12 3c3 4.2 6.1 7.5 6.1 11.2a6.1 6.1 0 1 1-12.2 0C5.9 10.5 9 7.2 12 3Zm-2.9 12.2c.3 1.1.9 1.8 2.1 2.1" />
    <path v-else-if="name === 'building'" d="M3 20h18M5 20V9h6v11m0-15h8v15m-8-15h8m-12 7h1m-1 3h1m6-7h2m-2 4h2m-2 4h2" />
    <path v-else-if="name === 'road'" d="m7 3-3 18m13-18 3 18M12 4v3m0 4v2m0 4v3" />
    <path v-else-if="name === 'arrow'" d="M5 12h14m-6-6 6 6-6 6" />
    <path v-else-if="name === 'external'" d="M13 5h6v6m-1-5-8 8m7-1v6H5V7h6" />
    <path v-else-if="name === 'close'" d="m6 6 12 12M18 6 6 18" />
    <path v-else-if="name === 'chevron'" d="m6 9 6 6 6-6" />
    <path v-else-if="name === 'upload'" d="M12 16V4m-4 4 4-4 4 4M4 15v5h16v-5" />
    <path v-else-if="name === 'download'" d="M12 4v12m-4-4 4 4 4-4M4 17v3h16v-3" />
    <path v-else-if="name === 'check'" d="m5 12 4.5 4.5L19 7" />
    <path v-else-if="name === 'location'" d="M12 21c1.6-2.3 6-6.3 6-10.5a6 6 0 0 0-12 0C6 14.7 10.4 18.7 12 21Z M12 10.5h.01" />
    <path v-else-if="name === 'info'" d="M12 11v6m0-10h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
    <path v-else-if="name === 'expand'" d="M4.5 9V4.5H9m6 0h4.5V9m0 6v4.5H15m-6 0H4.5V15" />
    <path v-else-if="name === 'collapse'" d="M4.5 9H9V4.5m6 0V9h4.5m0 6H15v4.5m-6 0V15H4.5" />
    <path v-else-if="name === 'play'" d="M8 5.5 19 12 8 18.5Z" fill="currentColor" stroke="none" />
    <path v-else-if="name === 'pause'" d="M9 5.5v13m6-13v13" stroke-width="2.4" />
    <path v-else-if="name === 'stats'" d="M4 19.5h16m-13-3v-4m5 4V5m5 11.5V9" />
    <path v-else-if="name === 'grid'" d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" />
    <path v-else-if="name === 'book'" d="M12 6c-2.2-1.5-5-2-8-1v13c3-1 5.8-.5 8 1 2.2-1.5 5-2 8-1V5c-3-1-5.8-.5-8 1Zm0 0v13" />
  </svg>
</template>
