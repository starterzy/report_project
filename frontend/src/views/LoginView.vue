<template>
  <div class="login-container">
    <el-card class="login-card">
      <template #header>
        <h2>报表系统登录</h2>
      </template>
      <el-form :model="form" @submit.prevent="handleLogin">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="请输入密码" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">
            登录
          </el-button>
        </el-form-item>
      </el-form>
      <el-divider>或</el-divider>
      <el-button type="success" style="width: 100%" @click="handleWeWorkLogin">
        企业微信登录
      </el-button>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus'
import { authApi } from '../api/auth'

const router = useRouter()
const authStore = useAuthStore()
const form = ref({ username: '', password: '' })
const loading = ref(false)

async function handleLogin() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await authStore.login(form.value.username, form.value.password)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (e) {
    ElMessage.error('登录失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function handleWeWorkLogin() {
  try {
    const response = await authApi.weworkRedirect()
    window.location.href = response.redirect_url
  } catch (e) {
    ElMessage.error('获取登录跳转链接失败')
  }
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card {
  width: 400px;
}
.demo-accounts {
  margin-top: 20px;
  padding: 10px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 12px;
  color: #666;
}
.demo-accounts p {
  margin: 5px 0;
}
</style>
