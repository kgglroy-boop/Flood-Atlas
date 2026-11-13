<script setup lang="ts">
import AtlasIcon from './AtlasIcon.vue';
import type { CaseStep, SceneChoice } from './atlas-cases';

defineProps<{
  choices: SceneChoice[];
  choice?: SceneChoice;
  step: CaseStep;
  comparison?: CaseStep;
  alternatives: CaseStep[];
  series: CaseStep[];
  playing: boolean;
}>();
defineEmits<{
  scene: [id: string];
  frame: [id: string];
  compare: [];
  reference: [id: string];
  play: [];
}>();
</script>

<template>
  <div class="scene-controls" aria-label="水深情景">
    <div class="scene-line">
      <div v-if="choices.length > 1 && choices.length <= 3" class="atlas-glass scene-switch" role="group" aria-label="切换水深情景">
        <button v-for="entry in choices" :key="entry.id" type="button" :aria-pressed="entry.id === choice?.id"
          @click="$emit('scene', entry.id)">{{ entry.label }}</button>
      </div>
      <select v-else-if="choices.length > 3" class="atlas-glass scene-select" aria-label="切换水深情景" :value="choice?.id"
        @change="$emit('scene', ($event.target as HTMLSelectElement).value)">
        <option v-for="entry in choices" :key="entry.id" :value="entry.id">{{ entry.label }}</option>
      </select>
      <button v-if="alternatives.length" class="atlas-glass scene-compare" type="button" aria-label="情景对照"
        :aria-pressed="!!comparison" @click="$emit('compare')"><AtlasIcon name="compare" :size="18" /> <span>对照</span></button>
    </div>
    <div v-if="comparison" class="atlas-glass scene-reference">
      <label for="reference-step">对照情景</label>
      <select id="reference-step" :value="comparison.id" @change="$emit('reference', ($event.target as HTMLSelectElement).value)">
        <option v-for="entry in alternatives" :key="entry.id" :value="entry.id">{{ entry.scenario === entry.label || entry.kind === 'peak' ? entry.label : entry.scenario + ' · ' + entry.label }}</option>
      </select>
    </div>
    <div v-if="series.length > 1" class="atlas-glass scene-timeline" aria-label="模拟时间轴">
      <button type="button" :aria-label="playing ? '暂停时间轴' : '播放时间轴'" @click="$emit('play')">
        <AtlasIcon :name="playing ? 'pause' : 'play'" :size="19" />
      </button>
      <input type="range" min="0" :max="series.length - 1" :value="series.findIndex(frame => frame.id === step.id)"
        aria-label="模拟时间" :aria-valuetext="step.time_min + ' 分钟'"
        @input="$emit('frame', series[Number(($event.target as HTMLInputElement).value)]!.id)" />
      <span>{{ step.time_min }} 分钟</span>
    </div>
  </div>
</template>

