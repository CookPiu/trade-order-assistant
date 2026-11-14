<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { errorMessage } from '@/api/http'
import { ROLE_HOME, useSessionStore } from '@/stores/session'

const session = useSessionStore()
const router = useRouter()
const route = useRoute()
const form = reactive({ username: '', password: '' })
const loading = ref(false)
const error = ref('')

async function submit() {
  if (!form.username || !form.password) {
    error.value = '请输入账号和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await session.login(form.username, form.password)
    const redirect = route.query.redirect as string | undefined
    if (redirect && redirect !== '/') {
      await router.replace(redirect)
    } else {
      await router.replace({ name: ROLE_HOME[session.user!.role] })
    }
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card app-panel">
      <h1>智能商贸提单助手</h1>
      <p class="sub">大宗物资销售与采购订单提单</p>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="账号">
          <el-input v-model="form.username" autocomplete="username" placeholder="请输入账号" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" placeholder="请输入密码" />
        </el-form-item>
        <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="err" />
        <el-button type="primary" native-type="submit" :loading="loading" class="btn">登录</el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, #183b69 0%, #1f4e8c 45%, #f2f4f7 45.1%);
  padding: 16px;
  box-sizing: border-box;
}
.login-card {
  width: 380px;
  max-width: 100%;
  padding: 32px 32px 24px;
  box-shadow: 0 12px 32px rgba(24, 59, 105, 0.18);
  h1 {
    margin: 0;
    font-size: 22px;
    color: #183b69;
  }
  .sub {
    margin: 6px 0 24px;
    color: var(--app-text-secondary);
  }
}
.err {
  margin-bottom: 12px;
}
.btn {
  width: 100%;
}
</style>
