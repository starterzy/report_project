<template>
  <div class="layout-container">
    <el-header class="layout-header">
      <div class="header-left">
        <h2 class="logo">重点工作任务填报</h2>
        <el-menu
          :default-active="$route.name"
          :ellipsis="false"
          mode="horizontal"
          background-color="#545c64"
          text-color="#fff"
          active-text-color="#ffd04b"
          router
          class="header-menu"
        >
          <el-menu-item index="/">首页</el-menu-item>
          <el-menu-item index="/tasks">任务列表</el-menu-item>
          <el-menu-item index="/approve" v-if="authStore.isApprover || authStore.isAdmin">审批</el-menu-item>
          <el-menu-item index="/admin" v-if="authStore.isAdmin">管理</el-menu-item>
        </el-menu>
      </div>
      <div class="header-right">
        <span>{{ authStore.user?.username }} ({{ authStore.user?.roles?.join(', ') }})</span>
        <el-button @click="handleLogout">退出</el-button>
      </div>
    </el-header>
    <el-main class="layout-main">
      <router-view />
    </el-main>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

function handleLogout() {
  authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.layout-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.layout-header {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #545c64;
  color: #fff;
  flex-shrink: 0;
  padding: 0 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
  height: 100%;
}

.logo {
  margin: 0;
  font-size: 16px;
  white-space: nowrap;
}

.header-menu {
  height: 100%;
  border: none;
}

.header-menu .el-menu-item {
  height: 100%;
  line-height: 48px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 15px;
  font-size: 14px;
}

.layout-main {
  flex: 1;
  background: #f0f2f5;
  padding: 12px;
  overflow: auto;
  box-sizing: border-box;
}
</style>