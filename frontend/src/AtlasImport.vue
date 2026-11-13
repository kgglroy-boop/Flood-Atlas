<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue';
import AtlasIcon from './AtlasIcon.vue';
import AtlasMap from './AtlasMap.vue';
import { requestJson, type CaseVersion, type ImportJob } from './atlas-cases';

const accessKey = defineModel<string>('accessKey', { required: true });
const props = defineProps<{ current?: CaseVersion }>();
const emit = defineEmits<{ published: [item?: CaseVersion] }>();
const dialog = ref<HTMLDialogElement>();
const titleHeading = ref<HTMLHeadingElement>();
const formMode = ref<'files' | 'archive'>('files');
const metadata = ref({ id: '', title: '', subtitle: '', description: '', threshold_m: 0.1, unit: 'm', srid: '' });
const archive = ref<File>();
const reuse = ref(false);
const optional = ref<Partial<Record<'buildings' | 'roads' | 'imagery' | 'water' | 'area', File>>>({});
const attachments = [
  { field: 'buildings', label: '建筑', accept: '.geojson,.gpkg' },
  { field: 'roads', label: '道路', accept: '.geojson,.gpkg' },
  { field: 'imagery', label: '航拍底图', accept: '.tif,.tiff' },
  { field: 'water', label: '常年水体', accept: '.geojson,.gpkg' },
  { field: 'area', label: '分析范围', accept: '.geojson,.gpkg' },
] as const;
type InputStep = { key: number; id: string; label: string; scenario: string; kind: 'peak' | 'time'; time_min: number | ''; file?: File };
let serial = 0;
function newStep(): InputStep {
  serial += 1;
  return { key: serial, id: 'step-' + serial, label: '', scenario: '', kind: 'peak', time_min: '' };
}
const steps = ref([newStep()]);
const previewStepId = ref('');
const job = ref<ImportJob>();
const busy = ref(false);
const error = ref('');
type JobAction = 'refresh' | 'publish';
const jobAction = ref<JobAction>();
const failedAction = ref<JobAction>();
const statusHeading = ref<HTMLElement>();
const recoveryInput = ref<HTMLInputElement>();
const network = new AbortController();
let pollTimer: number | undefined;
const previewSteps = computed(() => job.value?.case?.steps ?? job.value?.preview?.steps ?? []);
const previewStep = computed(() => previewSteps.value.find(step => step.id === previewStepId.value) ?? previewSteps.value[0]);
const jobRunning = computed(() => job.value && ['queued', 'processing', 'publishing'].includes(job.value.status));
const attachmentCount = computed(() => attachments.filter(({ field }) => optional.value[field]).length);
const jobLabels: Record<ImportJob['status'], string> = {
  queued: '排队中', processing: '处理中', preview: '预览就绪', publishing: '发布中', ready: '已发布', error: '处理失败',
};
const caseIdPattern = '[a-z0-9][a-z0-9_\\-]{0,47}';
const stepIdPattern = '[A-Za-z0-9][A-Za-z0-9_\\-]{0,47}';
const headers = () => ({ Authorization: 'Bearer ' + accessKey.value.trim() });

function open() { dialog.value?.showModal(); }
defineExpose({ open });
function firstFile(event: Event) { return (event.target as HTMLInputElement).files?.[0]; }

function revealInvalidField(event: Event) {
  if (!(event.target instanceof HTMLElement)) return;
  const disclosure = event.target.closest('details');
  if (disclosure) disclosure.open = true;
}

function updateJob(result: ImportJob) {
  job.value = result;
  previewStepId.value = previewStep.value?.id ?? '';
  if (result.status === 'ready') emit('published', result.case);
  if (jobRunning.value) {
    pollTimer = window.setTimeout(() => requestJob('refresh'), 1100);
  }
}

async function requestJob(action: JobAction) {
  const current = job.value;
  if (!current || jobAction.value) return;
  window.clearTimeout(pollTimer);
  if (!accessKey.value.trim()) {
    showJobError(action, '请输入本地访问密钥');
    return;
  }
  const publishing = action === 'publish';
  jobAction.value = action;
  try {
    updateJob(await requestJson<ImportJob>('/api/v2/imports/' + encodeURIComponent(current.id) + (publishing ? '/publish' : ''), {
      method: publishing ? 'POST' : 'GET', headers: headers(), signal: network.signal,
    }));
    const recovering = failedAction.value !== undefined;
    error.value = '';
    failedAction.value = undefined;
    if (recovering || publishing) focusStatus();
  } catch (problem) {
    if (!network.signal.aborted) {
      showJobError(action, problem instanceof Error ? problem.message : publishing ? '发布请求失败' : '无法查询导入进度');
    }
  } finally {
    jobAction.value = undefined;
  }
}

function showJobError(action: JobAction, message: string) {
  failedAction.value = action;
  error.value = message;
  void nextTick(() => {
    if (dialog.value?.open) recoveryInput.value?.focus();
  });
}

function focusStatus() {
  void nextTick(() => {
    if (dialog.value?.open) statusHeading.value?.focus();
  });
}

function retryJob() {
  if (failedAction.value) void requestJob(failedAction.value);
}

async function submit() {
  if (busy.value) return;
  error.value = '';
  if (!accessKey.value.trim()) {
    error.value = '请输入本地访问密钥';
    return;
  }
  const data = new FormData();
  if (formMode.value === 'archive') {
    if (!archive.value) return;
    data.append('archive', archive.value);
  } else {
    if (steps.value.some(step => !step.file)) return;
    if (new Set(steps.value.map(step => step.id.trim())).size !== steps.value.length) {
      error.value = '每个水深步骤需要唯一的标识';
      return;
    }
    const { srid, ...fields } = metadata.value;
    data.append('metadata', JSON.stringify({
      ...fields, id: fields.id.trim(), title: fields.title.trim(),
      ...(srid === '' ? {} : { srid: Number(srid) }),
      ...(reuse.value && props.current?.id === fields.id.trim() ? {reuse_version:props.current.version} : {}),
      steps: steps.value.map(step => ({
        id: step.id.trim(), label: step.label.trim(), scenario: step.scenario.trim(), kind: step.kind,
        ...(step.kind === 'time' ? { time_min: Number(step.time_min) } : {}),
      })),
    }));
    for (const step of steps.value) if (step.file) data.append('depths', step.file);
    for (const [field, file] of Object.entries(optional.value)) if (file) data.append(field, file);
  }
  busy.value = true;
  try {
    updateJob(await requestJson<ImportJob>('/api/v2/imports', {
      method: 'POST', body: data, headers: headers(), signal: network.signal,
    }));
    focusStatus();
  } catch (problem) {
    if (!network.signal.aborted) error.value = problem instanceof Error ? problem.message : '导入请求失败';
  } finally {
    busy.value = false;
  }
}

function reset() {
  job.value = undefined;
  previewStepId.value = '';
  error.value = '';
  failedAction.value = undefined;
  archive.value = undefined;
  reuse.value = false;
  steps.value = [newStep()];
  optional.value = {};
  if (dialog.value) dialog.value.scrollTop = 0;
  titleHeading.value?.focus();
}

onBeforeUnmount(() => {
  network.abort();
  window.clearTimeout(pollTimer);
});
</script>

<template>
  <dialog ref="dialog" class="atlas-dialog atlas-import-dialog" aria-labelledby="atlas-import-title">
    <header class="atlas-dialog-head">
      <div>
        <h2 id="atlas-import-title" ref="titleHeading" tabindex="-1">导入案例</h2>
        <p>上传水深栅格或图谱案例包，核对预览后发布。</p>
      </div>
      <form method="dialog"><button class="atlas-icon-button atlas-neutral" aria-label="关闭导入"><AtlasIcon name="close" /></button></form>
    </header>

    <form v-if="!job" class="atlas-import-form" @submit.prevent="submit" @invalid.capture="revealInvalidField">
      <div class="atlas-dialog-body">
        <fieldset :disabled="busy">
          <div class="atlas-form-tabs" aria-label="导入方式" role="group">
            <button type="button" :aria-pressed="formMode === 'files'" @click="formMode = 'files'">
              <AtlasIcon name="layers" :size="17" /> GIS 文件
            </button>
            <button type="button" :aria-pressed="formMode === 'archive'" @click="formMode = 'archive'">
              <AtlasIcon name="folder" :size="17" /> 案例 ZIP
            </button>
          </div>

          <fieldset v-show="formMode === 'archive'" :disabled="formMode !== 'archive'" class="import-source">
            <label class="atlas-field">
              <span>图谱案例包</span>
              <small>选择从图谱导出的 .zip 案例包。</small>
              <input type="file" accept=".zip,application/zip" required @change="archive = firstFile($event)" />
            </label>
          </fieldset>

          <fieldset v-show="formMode === 'files'" :disabled="formMode !== 'files'" class="import-source">
            <section class="import-section" aria-labelledby="import-case-details">
              <h3 id="import-case-details">案例信息</h3>
              <div class="atlas-form-grid">
                <label class="atlas-field">案例名称<input v-model.trim="metadata.title" required maxlength="100" /></label>
                <label class="atlas-field">案例标识<input v-model.trim="metadata.id" required :pattern="caseIdPattern" maxlength="48" placeholder="例如 nyc-ida" /></label>
              </div>
              <details class="import-disclosure">
                <summary>
                  <span>分析设置与案例说明</span>
                  <small>阈值 {{ metadata.threshold_m }} m · 栅格 {{ metadata.unit }}</small>
                  <AtlasIcon name="chevron" :size="17" />
                </summary>
                <div class="atlas-form-grid import-disclosure-content">
                  <label class="atlas-field">淹没阈值（m）<input v-model.number="metadata.threshold_m" required type="number" min="0" step="any" /></label>
                  <label class="atlas-field">水深文件单位<select v-model="metadata.unit"><option value="m">米 (m)</option><option value="cm">厘米 (cm)</option><option value="ft">英尺 (ft)</option></select></label>
                  <label class="atlas-field">分析坐标系（EPSG）<input v-model="metadata.srid" type="number" min="1" step="1" placeholder="例如 32618" /></label>
                  <label class="atlas-field">副标题<input v-model.trim="metadata.subtitle" maxlength="160" /></label>
                  <label class="atlas-field import-full-width">案例说明<textarea v-model.trim="metadata.description" rows="2" maxlength="2000"></textarea></label>
                </div>
              </details>
            </section>

            <section class="import-section atlas-import-files" aria-labelledby="import-depth-steps">
              <div class="import-steps-heading">
                <div>
                  <h3 id="import-depth-steps">水深步骤</h3>
                  <p>每个步骤上传一份 GeoTIFF 水深栅格。</p>
                </div>
                <button type="button" class="atlas-neutral" :disabled="steps.length >= 20" @click="steps.push(newStep())">
                  <AtlasIcon name="plus" :size="17" /> 添加步骤
                </button>
              </div>
              <fieldset v-for="(step, index) in steps" :key="step.key" class="atlas-file-step">
                <legend>步骤 {{ index + 1 }}</legend>
                <div class="atlas-form-grid">
                  <label class="atlas-field import-full-width">水深栅格<input type="file" required accept=".tif,.tiff" @change="step.file = firstFile($event)" /></label>
                  <label class="atlas-field">步骤名称<input v-model.trim="step.label" required maxlength="100" /></label>
                  <label class="atlas-field">情景名称<input v-model.trim="step.scenario" required maxlength="100" /></label>
                  <label class="atlas-field">类型<select v-model="step.kind"><option value="peak">峰值</option><option value="time">时间步</option></select></label>
                  <label class="atlas-field">步骤标识<input v-model.trim="step.id" required :pattern="stepIdPattern" maxlength="48" /></label>
                  <label v-if="step.kind === 'time'" class="atlas-field">经过时间（分钟）<input v-model.number="step.time_min" required type="number" min="0" step="any" /></label>
                </div>
                <button v-if="steps.length > 1" class="atlas-neutral import-remove-step" type="button" @click="steps.splice(index, 1)">移除此步骤</button>
              </fieldset>
            </section>

            <details class="import-disclosure">
              <summary>
                <span>可选图层</span>
                <small v-if="attachmentCount">已选 {{ attachmentCount }} 项</small>
                <AtlasIcon name="chevron" :size="17" />
              </summary>
              <div class="import-disclosure-content">
                <label v-if="current && metadata.id === current.id" class="import-reuse">
                  <input v-model="reuse" type="checkbox" />
                  <span>复用当前版本中未重新上传的底图和地物</span>
                </label>
                <div class="atlas-form-grid">
                  <label v-for="attachment in attachments" :key="attachment.field" class="atlas-field">
                    {{ attachment.label }}
                    <input type="file" :accept="attachment.accept" @change="optional[attachment.field] = firstFile($event)" />
                  </label>
                </div>
              </div>
            </details>
          </fieldset>

          <label class="atlas-field import-access-key">本地访问密钥
            <input v-model="accessKey" type="password" required autocomplete="off" spellcheck="false" />
          </label>
        </fieldset>
        <p v-if="error" class="atlas-error" role="alert">{{ error }}</p>
      </div>
      <footer class="atlas-dialog-footer"><button class="atlas-primary" type="submit" :disabled="busy"><AtlasIcon name="upload" :size="18" /> {{ busy ? '正在上传…' : '生成预览' }}</button></footer>
    </form>

    <template v-else>
      <div class="atlas-dialog-body">
        <div class="atlas-job" role="status">
          <span v-if="job.status === 'ready'" class="atlas-job-indicator"><AtlasIcon name="check" :size="19" /></span>
          <span v-else class="atlas-job-indicator" :class="{ 'atlas-job-running': jobRunning && !failedAction }"><AtlasIcon name="info" :size="19" /></span>
          <div><h3 ref="statusHeading" tabindex="-1">{{ jobLabels[job.status] }}</h3><p>{{ job.message }}</p></div>
        </div>

        <form v-if="failedAction" class="import-recovery" aria-label="恢复导入请求" @submit.prevent="retryJob">
          <p class="atlas-error" role="alert">{{ error }}</p>
          <div class="import-recovery-fields">
            <label class="atlas-field">本地访问密钥
              <input ref="recoveryInput" v-model="accessKey" type="password" required autocomplete="off" spellcheck="false" :disabled="!!jobAction" />
            </label>
            <button class="atlas-primary" type="submit" :disabled="!!jobAction">
              {{ failedAction === 'publish' ? (jobAction ? '正在发布…' : '重试发布') : (jobAction ? '正在查询…' : '刷新进度') }}
            </button>
          </div>
        </form>

        <ul v-if="job.preview?.warnings?.length" class="atlas-warnings"><li v-for="warning in job.preview.warnings" :key="warning">{{ warning }}</li></ul>
        <template v-if="previewStep">
          <label class="atlas-field">预览步骤<select v-model="previewStepId">
            <option v-for="step in previewSteps" :key="step.id" :value="step.id">{{ step.label }}</option>
          </select></label>
          <AtlasMap v-if="job.case && previewStep.depth" :key="job.case.id + '/' + job.case.version"
            class="atlas-import-map" :item="job.case" :step="previewStep" :online="false" :inspectable="false" />
          <dl class="atlas-preview-stats">
            <div><dt>淹没面积</dt><dd>{{ previewStep.summary.flooded_area_m2.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }} m²</dd></div>
            <div><dt>受影响建筑</dt><dd>{{ previewStep.summary.affected_buildings?.toLocaleString('zh-CN') ?? '—' }}</dd></div>
            <div><dt>受淹道路</dt><dd>{{ previewStep.summary.flooded_road_length_m == null ? '—' : previewStep.summary.flooded_road_length_m.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + ' m' }}</dd></div>
          </dl>
        </template>
      </div>
      <footer v-if="job.status === 'ready' || job.status === 'error' || (job.status === 'preview' && !failedAction)" class="atlas-dialog-footer">
        <button v-if="job.status === 'ready' || job.status === 'error'" type="button" class="atlas-neutral" @click="reset">重新导入</button>
        <button v-if="job.status === 'preview' && !failedAction" type="button" class="atlas-primary" :disabled="!!jobAction" @click="requestJob('publish')"><AtlasIcon name="check" :size="18" /> {{ jobAction ? '发布中…' : '发布此版本' }}</button>
        <form v-if="job.status === 'ready'" method="dialog"><button class="atlas-primary">返回图谱 <AtlasIcon name="arrow" :size="18" /></button></form>
      </footer>
    </template>
  </dialog>
</template>

<style scoped>
.atlas-import-dialog {
  scroll-padding-block: 100px 82px;
}

.atlas-form-tabs button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.import-source {
  display: grid;
  gap: 18px;
  padding-block: 10px;
}

.import-section {
  display: grid;
  gap: 10px;
}

.import-section h3,
.atlas-job h3 {
  font-size: 16px;
  font-weight: 640;
}

.import-section + .import-section,
.import-access-key {
  padding-top: 16px;
  border-top: 1px solid var(--edge);
}

.atlas-field > small,
.import-steps-heading p,
.import-disclosure small {
  color: var(--muted);
  font-size: 12px;
}

.import-disclosure {
  border: 1px solid var(--edge);
  border-radius: 12px;
}

.import-disclosure > summary {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 8px 12px;
  border-radius: inherit;
  list-style: none;
  cursor: pointer;
  font-size: 13px;
}

.import-disclosure > summary::-webkit-details-marker {
  display: none;
}

.import-disclosure > summary:hover {
  background: #ffffff14;
}

.import-disclosure > summary span {
  flex: 1;
}

.import-disclosure[open] > summary svg {
  transform: rotate(180deg);
}

.import-disclosure-content {
  padding: 12px;
  border-top: 1px solid var(--edge);
}

.import-steps-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.import-full-width {
  grid-column: 1 / -1;
}

.atlas-file-step legend {
  padding-inline: 6px;
  font-size: 13px;
}

.import-remove-step {
  margin-block: 6px 4px;
}

.import-reuse {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 44px;
  margin-bottom: 8px;
  cursor: pointer;
  font-size: 13px;
}

.import-reuse input {
  width: 17px;
  height: 17px;
  margin: 0;
  accent-color: var(--green);
}

.import-access-key {
  margin-top: 16px;
}

.import-recovery {
  margin: 14px 0;
  padding: 12px;
  border: 1px solid var(--edge);
  border-radius: 12px;
}

.import-recovery .atlas-error {
  margin: 0 0 10px;
}

.import-recovery-fields {
  display: flex;
  align-items: end;
  gap: 10px;
}

.import-recovery-fields .atlas-field {
  flex: 1;
  min-width: 0;
  margin: 0;
}

.atlas-import-map {
  position: relative;
  inset: auto;
  width: 100%;
  height: clamp(228px, 38dvh, 372px);
  border-radius: 12px;
}

.atlas-preview-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
  margin: 14px 0 0;
}

.atlas-preview-stats > div {
  padding: 10px 12px;
  border: 1px solid var(--edge);
  border-radius: 12px;
}

.atlas-preview-stats dt {
  color: var(--muted);
  font-size: 12px;
}

.atlas-preview-stats dd {
  font-variant-numeric: tabular-nums;
}

@media (max-width: 420px) {
  .import-recovery-fields {
    display: grid;
  }

  .import-disclosure > summary small {
    font-size: 11px;
  }
}
</style>
