import { createRouter, createWebHistory } from "vue-router";
import Chat from "./pages/Chat.vue";
import ActionLogs from "./pages/ActionLogs.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "chat", component: Chat },
    { path: "/action-logs", name: "action-logs", component: ActionLogs }
  ]
});

export default router;
