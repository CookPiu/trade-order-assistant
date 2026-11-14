<script setup lang="ts">
/** 参数配置（FR-051、D-014）：额度规则、固定业务属性、大模型调用参数，保存后下一次请求即生效。 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { errorMessage, http } from '@/api/http'

interface ParamView {
  key: string
  value: unknown
  default: unknown
  description: string
}
interface ModelParams {
  model: string
  temperature: number
  timeout: number
  thinking?: boolean
}

const loading = ref(false)
const saving = ref('')
const rules = reactive({ deviation: 10, warn: 10 })
const fixed = reactive({ biz_name: '', purchase_mode: '', biz_tag: '' })
const llm = reactive<ModelParams>({ model: '', temperature: 0.1, timeout: 30, thinking: false })
const vision = reactive<ModelParams>({ model: '', temperature: 0.1, timeout: 60 })

// 比例在界面上按百分数编辑，接口保存小数
const pct = (v: unknown) => Math.round(Number(v) * 1000) / 10

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<ParamView[]>('/params')
    const byKey = Object.fromEntries(data.map((p) => [p.key, p.value]))
    rules.deviation = pct(byKey.fair_price_deviation)
    rules.warn = pct(byKey.quota_warn_ratio)
    Object.assign(fixed, byKey.fixed_attrs)
    Object.assign(llm, byKey.llm)
    Object.assign(vision, byKey.vision)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    loading.value = false
  }
}

async function put(key: string, value: unknown) {
  await http.put(`/params/${key}`, { value })
}

async function save(section: 'rules' | 'fixed' | 'llm' | 'vision') {
  saving.value = section
  try {
    if (section === 'rules') {
      await put('fair_price_deviation', rules.deviation / 100)
      await put('quota_warn_ratio', rules.warn / 100)
    } else if (section === 'fixed') {
      if (!fixed.biz_name.trim() || !fixed.purchase_mode.trim() || !fixed.biz_tag.trim()) {
        ElMessage.warning('固定业务属性不能为空')
        return
      }
      await put('fixed_attrs', { ...fixed })
    } else if (section === 'llm') {
      await put('llm', { ...llm })
    } else {
      await put('vision', { ...vision })
    }
    ElMessage.success('已保存，下一次请求起生效')
    await load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="params">
    <section class="card">
      <header>
        <h3>额度与价格提醒</h3>
        <el-button type="primary" size="small" :loading="saving === 'rules'" @click="save('rules')">保存</el-button>
      </header>
      <el-form label-width="150px">
        <el-form-item label="公允价允许偏离">
          <el-input-number v-model="rules.deviation" :min="0.1" :max="100" :step="1" :precision="1" />
          <span class="unit">%</span>
          <p class="desc">单价偏离物料公允价超过该比例时提醒，不阻止提交。各物料的公允价在“物料字典与别名”中维护。</p>
        </el-form-item>
        <el-form-item label="履约配额阈值">
          <el-input-number v-model="rules.warn" :min="0" :max="99.9" :step="1" :precision="1" />
          <span class="unit">%</span>
          <p class="desc">提交后合同剩余金额低于合同总金额的该比例时提醒；金额超出剩余额度时仍需填写备注并转待特批。</p>
        </el-form-item>
      </el-form>
    </section>

    <section class="card">
      <header>
        <h3>固定业务属性</h3>
        <el-button type="primary" size="small" :loading="saving === 'fixed'" @click="save('fixed')">保存</el-button>
      </header>
      <el-form label-width="150px">
        <el-form-item label="业务名称">
          <el-input v-model="fixed.biz_name" maxlength="32" class="w" />
        </el-form-item>
        <el-form-item label="采购模式">
          <el-input v-model="fixed.purchase_mode" maxlength="16" class="w" />
        </el-form-item>
        <el-form-item label="业务标签">
          <el-input v-model="fixed.biz_tag" maxlength="16" class="w" />
          <p class="desc">新生成的草稿自动带入这三项，已提交订单不变。</p>
        </el-form-item>
      </el-form>
    </section>

    <section class="card">
      <header>
        <h3>文本模型（对话提单）</h3>
        <el-button type="primary" size="small" :loading="saving === 'llm'" @click="save('llm')">保存</el-button>
      </header>
      <el-form label-width="150px">
        <el-form-item label="模型名">
          <el-input v-model="llm.model" maxlength="64" placeholder="留空使用 .env 中的 DEEPSEEK_MODEL" class="w" />
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="llm.temperature" :min="0" :max="2" :step="0.1" :precision="2" />
        </el-form-item>
        <el-form-item label="超时">
          <el-input-number v-model="llm.timeout" :min="5" :max="300" :step="5" />
          <span class="unit">秒</span>
        </el-form-item>
        <el-form-item label="思考模式">
          <el-switch v-model="llm.thinking" />
          <p class="desc">打开后模型先推理再输出，单轮响应变慢。</p>
        </el-form-item>
      </el-form>
    </section>

    <section class="card">
      <header>
        <h3>视觉模型（图片识别）</h3>
        <el-button type="primary" size="small" :loading="saving === 'vision'" @click="save('vision')">保存</el-button>
      </header>
      <el-form label-width="150px">
        <el-form-item label="模型名">
          <el-input v-model="vision.model" maxlength="64" placeholder="留空使用 .env 中的 VISION_MODEL" class="w" />
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="vision.temperature" :min="0" :max="2" :step="0.1" :precision="2" />
        </el-form-item>
        <el-form-item label="超时">
          <el-input-number v-model="vision.timeout" :min="5" :max="300" :step="5" />
          <span class="unit">秒</span>
        </el-form-item>
      </el-form>
    </section>
  </div>
</template>

<style scoped lang="scss">
.params {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr));
  gap: 12px;
}
.card {
  border: 1px solid #e3e8ef;
  border-radius: 6px;
  padding: 10px 14px 4px;
  min-width: 0;
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  h3 {
    margin: 0;
    font-size: 14px;
  }
}
.unit {
  margin-left: 6px;
  color: var(--app-text-secondary);
}
.desc {
  margin: 4px 0 0;
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: var(--app-text-secondary);
}
.w {
  width: 100%;
  max-width: 280px;
}
@media (max-width: 600px) {
  .card :deep(.el-form-item) {
    flex-direction: column;
    align-items: flex-start;
  }
  .card :deep(.el-form-item__label) {
    justify-content: flex-start;
    width: auto !important;
  }
}
</style>
