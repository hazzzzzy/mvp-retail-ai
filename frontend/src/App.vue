<template>
  <Chat />
</template>

<script setup lang="ts">
import Chat from "./pages/Chat.vue";
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
</style>
