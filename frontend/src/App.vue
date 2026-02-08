<template>
  <div class="app-shell">
    <header class="top-nav">
      <el-menu
        :default-active="activePath"
        mode="horizontal"
        :ellipsis="false"
        @select="onSelect"
      >
        <el-menu-item index="/">聊天助手</el-menu-item>
        <el-menu-item index="/action-logs">执行日志</el-menu-item>
      </el-menu>
    </header>
    <main class="page-body">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
const activePath = computed(() => route.path);

function onSelect(path: string) {
  if (path !== route.path) router.push(path);
}
</script>

<style>
:root {
  font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
  color: #1f2937;
  background: radial-gradient(circle at top right, #d9f99d, #f8fafc 45%);
}

* {
  box-sizing: border-box;
}

html,
body,
#app {
  height: 100%;
  overflow: hidden;
}

body {
  margin: 0;
}

.app-shell {
  height: 100%;
  display: grid;
  grid-template-rows: 56px 1fr;
}

.top-nav {
  border-bottom: 1px solid #e5e7eb;
  background: #ffffffd9;
  backdrop-filter: blur(6px);
}

.top-nav .el-menu {
  border-bottom: none;
  padding: 0 16px;
}

.page-body {
  min-height: 0;
  overflow: hidden;
}
</style>
